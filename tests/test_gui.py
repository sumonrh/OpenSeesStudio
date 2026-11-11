"""GUI workflow tests (headless, real Qt platform)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from app import dialogs, mainwindow, results as results_mod  # noqa: E402
from app.mainwindow import MainWindow  # noqa: E402
from app.model import Project  # noqa: E402
from app.tables import TablesDialog  # noqa: E402

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

print("== static analysis through the GUI ==")
mainwindow.ResultsDialog = StubResults
win.run_static()
check("static results present", win.static_results is not None)
check("max displacement reasonable", 0.0 < win.static_results.max_disp < 20.0,
      f"({win.static_results.max_disp:.4f} mm)")
check("viewport shows deformed shape",
      bool(win.viewport._deformed_points()))

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
check("table edit applied", abs(p2.nodes[1].x - 250.0) < 1e-9)
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
