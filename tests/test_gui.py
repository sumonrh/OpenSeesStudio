"""GUI workflow tests (headless, real Qt platform)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (QApplication, QLabel, QTableWidgetSelectionRange,
                               QToolButton)

app = QApplication.instance() or QApplication([])

from app import dialogs, mainwindow, results as results_mod, steelsections  # noqa: E402
from app.mainwindow import MainWindow  # noqa: E402
from app.model import Project, Section  # noqa: E402
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
    previewChanged = StubSig()

    def __init__(self, *a, **k):
        pass

    def exec(self):
        return 1

    def refresh_preview(self):
        pass

    def spec(self):
        return (0, 3000.0, True, True)


class FakeSubdivide:
    def __init__(self, *a, **k):
        pass

    def exec(self):
        return 1

    def spec(self):
        return 4


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
view_page = win.ribbon._pages[0]
check("view tab has no deformed button",
      all(b.defaultAction() is not win.a_deformed
          for b in view_page.findChildren(QToolButton)))
results_page = win.ribbon._pages[7]
result_actions = [b.defaultAction() for b in results_page.findChildren(QToolButton)]
check("results tab has diagrams and deformation",
      win.a_beam_diagram in result_actions and win.a_deformation in result_actions)
check("properties panel action", win.a_props_visible.isChecked())
win.a_props_visible.trigger()
check("properties panel collapses", win.props_dock.isHidden())
win.a_props_visible.trigger()
check("properties panel restores", not win.props_dock.isHidden())
root = win.tree.topLevelItem(0)
tree_items = {root.child(i).text(0).split("   ")[0]: root.child(i)
              for i in range(root.childCount())}
check("nodes tree is a table link", tree_items["Nodes"].childCount() == 0)
check("elements tree is a table link", tree_items["Elements"].childCount() == 0)
orig_open_tables = win.open_tables
table_calls = []
win.open_tables = lambda tab=0: table_calls.append(tab)
win._tree_clicked(tree_items["Nodes"], 0)
win._tree_clicked(tree_items["Elements"], 0)
win.open_tables = orig_open_tables
check("tree links open tables", table_calls == [0, 2], f"({table_calls})")
mat_item = tree_items["Materials"].child(0)
win._tree_double(mat_item, 0)
check("tree material selects elements", len(win.viewport.sel_elements) > 0)
check("analysis icons are unique",
      len({win.a_run.icon().cacheKey(), win.a_modal.icon().cacheKey(),
           win.a_animate.icon().cacheKey()}) == 3)
check("library icons are unique",
      win.a_material.icon().cacheKey() != win.a_section.icon().cacheKey())

win.a_extruded.trigger()
check("extruded view enabled", win.viewport.show_extruded)
vp_shot = win.viewport.grab()
check("extruded view renders", not vp_shot.isNull() and vp_shot.width() > 0)
win.a_extruded.trigger()

win.clean_view()
check("clean view hides results and loads",
      not win.viewport.show_deformed and not win.viewport.show_loads
      and not win.viewport.show_labels)
win.viewport.set_show(show_deformed=True, show_loads=True)
win.a_deformed.setChecked(True)
win.a_loads_visible.setChecked(True)

check("tree lists materials",
      tree_items["Materials"].childCount() == len(win.project.materials))
check("tree lists sections",
      tree_items["Sections"].childCount() == len(win.project.sections))
loads_item = tree_items["Loads"]
load_cases_item = next(loads_item.child(i) for i in range(loads_item.childCount())
                       if loads_item.child(i).text(0).startswith("Load Cases"))
check("tree lists load cases",
      load_cases_item.childCount() == len(win.project.cases))
check("load tree has no per-element load rows",
      all(not loads_item.child(i).text(0).startswith(("Nodal Loads", "Element Loads"))
          for i in range(loads_item.childCount())))
case0 = load_cases_item.child(0)
win._tree_double(case0, 0)
check("double-click case selects loaded elements",
      len(win.viewport.sel_elements) > 0)
win._display_load_case("LL", True)
check("load case display", win.viewport.load_filter_active
      and "LL" in win.viewport.display_cases and win.viewport.show_loads)
win._display_load_case("LL", False)
check("load case undisplay", "LL" not in win.viewport.display_cases)
win._scenario_changed("DL")
check("scenario restores normal load display",
      not win.viewport.load_filter_active and win.viewport.show_loads)

print("== static analysis through the GUI ==")
mainwindow.ResultsDialog = StubResults
win.run_static()
check("static results present", win.static_results is not None)
check("max displacement reasonable", 0.0 < win.static_results.max_disp < 20.0,
      f"({win.static_results.max_disp:.4f} mm)")
check("viewport shows deformed shape",
      bool(win.viewport._deformed_points()))
check("analysis switches to results tab", win.ribbon.current_title() == "Results")
win.a_beam_diagram.trigger()
check("beam diagrams open", win.viewport.show_diagrams
      and not win.results_dock.isHidden())
check("load case results cached", win.results_scenario in win.static_cache)
win.a_beam_diagram.trigger()
check("beam diagrams clear", not win.viewport.show_diagrams)
win.viewport.show_deformed = True
win.a_deformed.setChecked(True)
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
win.viewport.select_nodes(base_nodes)
n1 = len(win.project.nodes)
old_mirror = dialogs.MirrorDialog
dialogs.MirrorDialog = FakeMirror
win.mirror()
dialogs.MirrorDialog = old_mirror
check("mirror added nodes", len(win.project.nodes) == n1 + 8,
      f"({len(win.project.nodes) - n1} added)")
mirrored = [win.project.nodes[t] for t in win.viewport.sel_nodes]
check("mirror uses plane coordinate",
      bool(mirrored) and all(abs(n.x - 6000.0) < 1e-6 for n in mirrored),
      f"(x={mirrored[0].x if mirrored else 'none'})")
md = dialogs.MirrorDialog(win)
md.plane.setCurrentIndex(2)
md.coordinate.setValue(6.0)
axis, offset, _, _ = md.spec()
check("mirror dialog coordinate converted", axis == 0 and abs(offset - 6000.0) < 1e-6)
win.viewport.set_mirror_plane(0, 6000.0)
check("mirror plane preview set", win.viewport.mirror_plane == (0, 6000.0))
win.viewport.clear_mirror_plane()
check("mirror plane preview cleared", win.viewport.mirror_plane is None)

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
dlg_case = TablesDialog(win.project, case_filter="LL")
visible = [r for r in range(dlg_case.page_eleload.table.rowCount())
           if not dlg_case.page_eleload.table.isRowHidden(r)]
check("load table filters by case",
      bool(visible) and all(dlg_case.page_eleload.table.item(r, 2).text() == "LL"
                            for r in visible))
check("load table keeps other cases",
      len(dlg_case._collect().elem_loads) == len(win.project.elem_loads))

dlg = TablesDialog(win.project)
dlg.page_nodes.table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, 3), True)
dlg.page_nodes.table.copy_selection()
check("table copies tab-separated text", "\t" in QApplication.clipboard().text())
QApplication.clipboard().setText("1\t1.5\t2.5\t3.5\n2\t4.0\t5.0\t6.0")
dlg.page_nodes.table.setCurrentCell(0, 0)
dlg.page_nodes.table.paste_clipboard()
p_paste = dlg._collect()
check("table pastes Excel block",
      abs(p_paste.nodes[1].x - UNITS.length_base(1.5)) < 1e-9
      and abs(p_paste.nodes[2].z - UNITS.length_base(6.0)) < 1e-9)
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
check("AISC database loaded", len(steelsections.AISC["W"][1]) > 250)
check("CISC database loaded", len(steelsections.CISC["W"][1]) > 250)
sd.tabs.setCurrentIndex(0)
sd.db.setCurrentIndex(sd.db.findData("AISC"))
sd.family.setCurrentIndex(sd.family.findData("W"))
row = sd._find_designation("W12X26")
sd.standard_table.selectRow(row)
check("AISC W section selected",
      sd.current.is_standard and sd.current.designation == "W12X26"
      and abs(sd.current.A - 4940.0) < 1e-6
      and abs(sd.current.Iy - 84.9e6) < 1e3,
      f"({sd.current.A:.0f} mm²)")
sd.db.setCurrentIndex(sd.db.findData("CISC"))
sd.family.setCurrentIndex(sd.family.findData("W"))
row = sd._find_designation("W310x39")
sd.standard_table.selectRow(row)
check("CISC W section selected",
      sd.current.designation == "W310x39"
      and abs(sd.current.A - 4940.0) < 1e-6)
sd.tabs.setCurrentIndex(1)
sd.shape.setCurrentIndex(sd.shape.findData("Hexagon"))
check("custom hexagonal shape", sd.current.shape == "Hexagon"
      and sd.current.catalog == "Custom" and sd.current.A > 0)

p_std = win.project.clone()
s_std = Section(999, "W12X26", "I-Shape", b=165.0, h=310.0, d=310.0,
                t=0.0, tw=5.84, tf=9.65)
s_std.A, s_std.Iy, s_std.Iz, s_std.J = 4940.0, 84.9e6, 7.2e6, 125000.0
s_std.catalog, s_std.designation, s_std.family = "AISC", "W12X26", "W"
p_std.sections[999] = s_std
td_std = TablesDialog(p_std)
p_std2 = td_std._collect()
check("standard section properties survive tables",
      abs(p_std2.sections[999].A - 4940.0) < 1e-6
      and abs(p_std2.sections[999].Iy - 84.9e6) < 1.0)

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

print("== delete a load case ==")
if win.model_locked:
    win.a_lock.trigger()
old_box = mainwindow.QMessageBox


class YesBox:
    Yes = old_box.Yes

    @staticmethod
    def question(*_args, **_kwargs):
        return old_box.Yes


mainwindow.QMessageBox = YesBox
try:
    win._delete_load_case("WIND")
finally:
    mainwindow.QMessageBox = old_box
check("load case deleted", "WIND" not in win.project.cases)
check("deleted case loads removed",
      all(load.case != "WIND" for load in win.project.nodal_loads + win.project.elem_loads))
check("deleted case removed from combinations",
      all(all(case != "WIND" for case, _f in combo.factors)
          for combo in win.project.combos.values()))

print("== element subdivision ==")
target = next(t for t, e in win.project.elements.items()
              if e.kind == "beam" and len(e.nodes) == 2)
n_before, e_before = len(win.project.nodes), len(win.project.elements)
win.viewport.select_elements([target])
old_subdivide = dialogs.SubdivideDialog
dialogs.SubdivideDialog = FakeSubdivide
win.subdivide()
dialogs.SubdivideDialog = old_subdivide
check("subdivide replaced original", target not in win.project.elements)
check("subdivide created four segments",
      len(win.project.elements) == e_before - 1 + 4,
      f"({len(win.project.elements) - e_before:+d} elements)")
check("subdivide added intermediate nodes",
      len(win.project.nodes) == n_before + 3,
      f"({len(win.project.nodes) - n_before:+d} nodes)")
check("subdivide selects new segments", len(win.viewport.sel_elements) == 4)

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
