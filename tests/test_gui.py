"""GUI workflow tests (headless, real Qt platform)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

app = QApplication.instance() or QApplication([])

from app import dialogs, mainwindow, results as results_mod  # noqa: E402
from app.mainwindow import MainWindow  # noqa: E402
from app.model import Project  # noqa: E402
from app.tables import TablesDialog  # noqa: E402
from app.units import UNITS  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        FAILS.append(name)


class StubSig:
    def connect(self, *a):
        pass


class StubResults:
    plotStatic = StubSig()
    plotMode = StubSig()

    def __init__(self, *a, **k):
        pass

    def exec(self):
        return 0


class FakeCount:
    def __init__(self, v):
        self._v = v

    def value(self):
        return self._v


class FakeCheck:
    def __init__(self, v):
        self._v = v

    def isChecked(self):
        return self._v


class FakeCopy:
    def __init__(self, *a, **k):
        self.count = FakeCount(1)
        self.keep_selection = FakeCheck(True)
        self.with_elements = FakeCheck(True)

    def exec(self):
        return 1

    def delta(self):
        return (18000.0, 0.0, 0.0)

    def is_copy(self):
        return True


class FakeMirror:
    def __init__(self, *a, **k):
        pass

    def exec(self):
        return 1

    def spec(self):
        return (0, True, True)


class FakeSupport:
    def __init__(self, project, selected, *a, **k):
        self._target = selected

    def exec(self):
        return 1

    def target(self):
        return self._target

    def support(self):
        return [True] * 6


class FakeNodalLoad:
    def __init__(self, project, selected, *a, **k):
        self._target = selected
        self.case = type("C", (), {"currentText": lambda s: "WIND"})()
        self.replace = FakeCheck(True)

    def exec(self):
        return 1

    def target(self):
        return self._target

    def values(self):
        return [50.0, 0, 0, 0, 0, 0]


class FakeElementLoad:
    def __init__(self, project, selected, *a, **k):
        self._target = selected
        self.case = type("C", (), {"currentText": lambda s: "LL"})()
        self.replace = FakeCheck(False)

    def exec(self):
        return 1

    def target(self):
        return self._target

    def spec(self):
        return {"kind": "uniform", "trapezoid": False, "direction": "Global Z",
                "value": -0.02, "value2": 0.0, "position": 0.5}


print("== window bootstrap ==")
win = MainWindow()
check("default project loads", len(win.project.nodes) == 0)
win.load_example()
check("example frame nodes", len(win.project.nodes) == 24, f"({len(win.project.nodes)})")
check("example frame elements", len(win.project.elements) == 39)
check("example load cases", len(win.project.cases) == 3)

print("== orbit control ==")
vp = win.viewport


def drag(x0, y0, x1, y1, mods=Qt.NoModifier):
    vp.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(x0, y0),
                                   QPointF(x0, y0), Qt.LeftButton, Qt.LeftButton, mods))
    vp.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(x1, y1),
                                  QPointF(x1, y1), Qt.NoButton, Qt.LeftButton, mods))
    vp.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(x1, y1),
                                     QPointF(x1, y1), Qt.LeftButton, Qt.NoButton, mods))


yaw0 = vp.camera.yaw
drag(400, 300, 480, 340)
check("plain left-drag does not orbit", abs(vp.camera.yaw - yaw0) < 1e-9,
      f"(dyaw={vp.camera.yaw - yaw0:.5f})")

win.a_orbit.trigger()
check("orbit mode enabled", vp.orbit_mode is True)
yaw1 = vp.camera.yaw
drag(400, 300, 520, 360)
check("orbit drag rotates", abs(vp.camera.yaw - yaw1) > 1e-4,
      f"(dyaw={vp.camera.yaw - yaw1:.4f})")
win.a_orbit.trigger()
check("orbit mode disabled", vp.orbit_mode is False)

yaw2 = vp.camera.yaw
drag(400, 300, 470, 330, Qt.ShiftModifier)
check("Shift+left orbits", abs(vp.camera.yaw - yaw2) > 1e-4,
      f"(dyaw={vp.camera.yaw - yaw2:.4f})")

print("== ribbon ==")
titles = [win.ribbon.tabs.tabText(i) for i in range(win.ribbon.tabs.count())]
check("ribbon tabs", titles == ["View", "Structure", "Node/Element", "Properties",
                                "Boundary", "Load", "Analysis", "Results", "Tools"],
      f"({titles})")
check("default ribbon tab", win.ribbon.current_title() == "Structure",
      f"({win.ribbon.current_title()})")
check("ribbon group captions", len(win.ribbon.findChildren(QLabel, "ribbonCaption")) >= 5)
check("ribbon app menu", len(win.ribbon.app_menu.actions()) >= 8)
check("ribbon actions wired",
      any(b.defaultAction() is win.a_nodes
          for b in win.ribbon.findChildren(QToolButton)))
grid_button = next(b for b in win.ribbon.findChildren(QToolButton)
                   if b.defaultAction() is win.a_grid)
grid_before = win.viewport.show_grid
grid_button.click()
check("ribbon button triggers action", win.viewport.show_grid != grid_before)
grid_button.click()
win.ribbon.set_current("Load")
check("ribbon tab switching", win.ribbon.current_title() == "Load")
win.ribbon.set_current("Structure")
check("quick access toolbar", win.a_run in win.quick_toolbar.actions())
check("quick view toolbar", win.a_fit in win.quick_view_toolbar.actions()
      and win.a_orbit in win.quick_view_toolbar.actions())
check("properties panel action", win.a_props_visible.isChecked())
win.a_props_visible.trigger()
check("properties panel collapses", win.props_dock.isHidden())
win.a_props_visible.trigger()
check("properties panel restores", not win.props_dock.isHidden())

root = win.tree.topLevelItem(0)
tree_items = {root.child(i).text(0).split("   ")[0]: root.child(i)
              for i in range(root.childCount())}
check("tree lists materials",
      tree_items["Materials"].childCount() == len(win.project.materials))
check("tree lists sections",
      tree_items["Sections"].childCount() == len(win.project.sections))
loads_item = tree_items["Loads"]
load_cases_item = next(loads_item.child(i) for i in range(loads_item.childCount())
                       if loads_item.child(i).text(0).startswith("Load Cases"))
check("tree lists load cases",
      load_cases_item.childCount() == len(win.project.cases))

print("== static analysis through the GUI ==")
mainwindow.ResultsDialog = StubResults
win.run_static()
check("static results present", win.static_results is not None)
check("max displacement reasonable", 0.0 < win.static_results.max_disp < 20.0,
      f"({win.static_results.max_disp:.4f} mm)")
check("viewport shows deformed shape",
      bool(win.viewport._deformed_points()))
check("analysis switches to results tab", win.ribbon.current_title() == "Results")
check("model auto-locked after analysis",
      win.model_locked and win.a_lock.isChecked() and not win.a_nodes.isEnabled())
win.a_lock.trigger()
check("lock toggle unlocks", not win.model_locked and win.a_nodes.isEnabled())

print("== load combination scenario ==")
win.scenario_combo.setCurrentText("1.4DL+1.6LL")
win.run_static()
combined = win.static_results.max_disp
check("combination amplifies DL", combined > 1.3 * 1.378, f"({combined:.3f} mm)")

print("== modal analysis (clean model) ==")
win.run_modal()
check("modal results present", win.modal_results is not None and len(win.modal_results.modes) > 0)
check("first period positive", win.modal_results.modes[0].period > 0,
      f"(T1={win.modal_results.modes[0].period:.4f} s)")
check("modal analysis locks model", win.model_locked and not win.a_nodes.isEnabled())
win.a_lock.trigger()
check("model unlocked for editing", not win.model_locked and win.a_nodes.isEnabled())

print("== copy / move ==")
base_nodes = [t for t, n in win.project.nodes.items() if abs(n.x) < 1e-6]
win.viewport.select_nodes(base_nodes)
n0, e0 = len(win.project.nodes), len(win.project.elements)
old_copy = dialogs.CopyMoveDialog
dialogs.CopyMoveDialog = FakeCopy
win.copy_move()
dialogs.CopyMoveDialog = old_copy
check("copy added nodes", len(win.project.nodes) == n0 + 8,
      f"({len(win.project.nodes) - n0} added)")
check("copy added attached elements", len(win.project.elements) == e0 + 9,
      f"({len(win.project.elements) - e0} added)")

print("== mirror ==")
n1 = len(win.project.nodes)
old_mirror = dialogs.MirrorDialog
dialogs.MirrorDialog = FakeMirror
win.mirror()
dialogs.MirrorDialog = old_mirror
check("mirror added nodes", len(win.project.nodes) == n1 + 8,
      f"({len(win.project.nodes) - n1} added)")

print("== undo / redo ==")
win.undo()
check("undo removed mirror nodes", len(win.project.nodes) == n1)
win.undo()
check("undo removed copied nodes", len(win.project.nodes) == n0)
win.redo()
check("redo restored copied nodes", len(win.project.nodes) == n1)
win.redo()
check("redo restored mirror", len(win.project.nodes) == n1 + 8)

print("== supports and loads ==")
win.viewport.select_nodes([1])
old_support = dialogs.SupportDialog
dialogs.SupportDialog = FakeSupport
win.assign_supports()
dialogs.SupportDialog = old_support
check("support assigned", win.project.nodes[1].support == [True] * 6)

old_nl = dialogs.NodalLoadDialog
dialogs.NodalLoadDialog = FakeNodalLoad
win.viewport.select_nodes([2])
win.nodal_loads()
dialogs.NodalLoadDialog = old_nl
check("nodal load added", any(l.node == 2 and l.case == "WIND"
                              and abs(l.values[0] - 50) < 1e-9
                              for l in win.project.nodal_loads))

old_el = dialogs.ElementLoadDialog
dialogs.ElementLoadDialog = FakeElementLoad
win.viewport.select_elements([1])
win.element_loads()
dialogs.ElementLoadDialog = old_el
check("element load added", any(l.elem == 1 and l.case == "LL"
                                for l in win.project.elem_loads))

print("== tables dialog round trip ==")
dlg = TablesDialog(win.project)
dlg.page_nodes.table.item(0, 1).setText("250")
p2 = dlg._collect()
check("table edit applied", abs(p2.nodes[1].x - UNITS.length_base(250.0)) < 1e-9)
dlg.page_nodes.table.item(0, 1).setText("not-a-number")
try:
    dlg._collect()
    check("table validation rejects text", False)
except ValueError:
    check("table validation rejects text", True)

print("== save / load ==")
tmp = os.path.join(tempfile.gettempdir(), "oss_roundtrip.ospj")
win.project.save(tmp)
loaded = Project.load(tmp)
check("save/load node count", len(loaded.nodes) == len(win.project.nodes))
check("save/load element count", len(loaded.elements) == len(win.project.elements))
check("save/load combos", list(loaded.combos) == list(win.project.combos))
check("save/load self weight", loaded.self_weight == win.project.self_weight)

print("== unit selector ==")
check("default force unit", win.units_force.currentText() == "kN",
      f"({win.units_force.currentText()})")
check("default length unit", win.units_length.currentText() == "m",
      f"({win.units_length.currentText()})")

n0 = win.project.nodes[9]
x0 = n0.x
win.units_force.setCurrentText("N")
win.units_length.setCurrentText("m")
check("unit globals applied", UNITS.force_unit == "N" and UNITS.length_unit == "m")
check("model stays in base units", abs(win.project.nodes[9].x - x0) < 1e-9,
      f"({win.project.nodes[9].x})")
win.viewport.select_nodes([9])
check("node props converted", abs(win.nd_x.value() - x0 / 1000.0) < 1e-6,
      f"({win.nd_x.value():.3f} m)")

dlg_u = TablesDialog(win.project)
row5 = next(r for r in range(dlg_u.page_nodes.table.rowCount())
            if dlg_u.page_nodes.table.item(r, 0).text() == "9")
shown_x = float(dlg_u.page_nodes.table.item(row5, 1).text())
check("tables converted", abs(shown_x - x0 / 1000.0) < 1e-6, f"({shown_x} m)")
collected = dlg_u._collect()
check("tables convert back", abs(collected.nodes[9].x - x0) < 1e-3,
      f"({collected.nodes[9].x:.3f} mm)")

nl = win.project.nodal_loads[0]
rowl = next(r for r in range(dlg_u.page_nodal.table.rowCount())
            if dlg_u.page_nodal.table.item(r, 0).text() == str(nl.tag))
shown_f = float(dlg_u.page_nodal.table.item(rowl, 3).text())
check("load table converted", abs(shown_f - UNITS.force(nl.values[0])) < 1e-6,
      f"({shown_f} N)")
got_nl = next(l for l in collected.nodal_loads if l.tag == nl.tag)
check("load table converts back", abs(got_nl.values[0] - nl.values[0]) < 1e-3)

sec = next(iter(win.project.sections.values()))
rows = next(r for r in range(dlg_u.page_sections.table.rowCount())
            if dlg_u.page_sections.table.item(r, 0).text() == str(sec.tag))
shown_b = float(dlg_u.page_sections.table.item(rows, 3).text())
check("section table converted", abs(shown_b - sec.b / 1000.0) < 1e-6,
      f"({shown_b} m)")
got_sec = next(s for s in collected.sections.values() if s.tag == sec.tag)
check("section table converts back", abs(got_sec.b - sec.b) < 1e-3)

win.nd_x.setValue(win.nd_x.value() + 1.0)
win._apply_node_props()
check("node props write converted", abs(win.project.nodes[9].x - (x0 + 1000.0)) < 1e-3,
      f"({win.project.nodes[9].x:.3f} mm)")
win.undo()
check("node props edit undone", abs(win.project.nodes[9].x - x0) < 1e-9)

nd = dialogs.NodeDialog(win.project)
nd.x.setValue(2.0)
check("node dialog converts", abs(nd.positions()[0][0] - 2000.0) < 1e-9)

ed = dialogs.ElementDialog(win.project, [])
ed.thickness.setValue(0.05)
check("element dialog converts", abs(ed.spec()["thickness"] - 50.0) < 1e-9)

md = dialogs.MaterialDialog(win.project)
mtag = next(iter(md.materials))
md.E.setValue(2.1e11)
check("material dialog converts", abs(md.materials[mtag].E - 210.0) < 1e-6,
      f"({md.materials[mtag].E:.3f} kN/mm²)")

sd = dialogs.SectionDialog(win.project)
sd.b.setValue(0.5)
check("section dialog converts", abs(sd.current.b - 500.0) < 1e-6,
      f"({sd.current.b:.3f} mm)")

UNITS.set("kip", "ft")
dlg_ft = TablesDialog(win.project)
p_ft = dlg_ft._collect()
ft_err = max(abs(p_ft.nodes[t].x - win.project.nodes[t].x)
             for t in win.project.nodes)
check("ft table round trip", ft_err < 0.01, f"(max {ft_err:.5f} mm)")
sec_ft = next(s for s in p_ft.sections.values() if s.tag == sec.tag)
check("ft section round trip", abs(sec_ft.b - sec.b) < 0.01,
      f"({sec_ft.b:.4f} mm)")

UNITS.set("kip", "ft")
check("kip conversion", abs(UNITS.force(1.0) - 0.2248089431) < 1e-9,
      f"({UNITS.force(1.0):.6f} kip)")
check("ft conversion", abs(UNITS.length(304.8) - 1.0) < 1e-12)
m0 = 1000.0
check("moment round trip", abs(UNITS.moment_base(UNITS.moment(m0)) - m0) < 1e-9)

win.units_force.setCurrentText("kN")
win.units_length.setCurrentText("m")
check("units restored", UNITS.force_unit == "kN" and UNITS.length_unit == "m")

print("== disconnected nodes are rejected ==")
from app import opsgen
from app.model import Node
orphan = win.project.next_node()
win.project.nodes[orphan] = Node(orphan, 99999.0, 0.0, 0.0)
try:
    opsgen.run_modal(win.project, 3)
    check("orphan nodes rejected", False)
except ValueError as exc:
    check("orphan nodes rejected", "not connected" in str(exc),
          f"({str(exc).splitlines()[-1][:60]})")
del win.project.nodes[orphan]

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("ALL GUI TESTS PASSED")
