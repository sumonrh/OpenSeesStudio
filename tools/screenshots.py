"""Generate screenshots of the main window and key dialogs."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app import dialogs, opsgen
from app.mainwindow import MainWindow
from app.results import ResultsDialog
from app.tables import TablesDialog

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "shots")
os.makedirs(OUT, exist_ok=True)

app = QApplication.instance() or QApplication([])
from app import theme  # noqa: E402

theme.apply_theme(app)

win = MainWindow()
win.resize(1500, 900)
win.show()
win.load_example()
win.scenario_combo.setCurrentText("1.4DL+1.6LL")
win.run_static()


def grab(widget, name):
    widget.grab().save(os.path.join(OUT, name))
    print("saved", name)


def do_shots():
    app.processEvents()
    grab(win, "01_main_static.png")

    d = dialogs.NodeDialog(win.project, win)
    d.show()
    app.processEvents()
    grab(d, "02_node_dialog.png")
    d.close()

    sel = [t for t, n in win.project.nodes.items() if abs(n.z) < 1e-6][:2]
    d = dialogs.ElementDialog(win.project, sel, win)
    d.show()
    app.processEvents()
    grab(d, "03_element_dialog.png")
    d.close()

    d = dialogs.CopyMoveDialog("Copy / Move", win)
    d.show()
    app.processEvents()
    grab(d, "04_copy_move.png")
    d.close()

    d = dialogs.SupportDialog(win.project, list(win.project.nodes)[:6], win)
    d.show()
    app.processEvents()
    grab(d, "05_supports.png")
    d.close()

    d = dialogs.NodalLoadDialog(win.project, list(win.project.nodes)[:3], win)
    d.show()
    app.processEvents()
    grab(d, "06_nodal_loads.png")
    d.close()

    d = dialogs.LoadCaseDialog(win.project, win)
    d.show()
    app.processEvents()
    grab(d, "07_load_cases.png")
    d.close()

    d = dialogs.ComboDialog(win.project, win)
    d.show()
    app.processEvents()
    grab(d, "08_combinations.png")
    d.close()

    d = dialogs.SectionDialog(win.project, win)
    d.show()
    app.processEvents()
    grab(d, "09_sections.png")
    d.close()

    d = dialogs.MaterialDialog(win.project, win)
    d.show()
    app.processEvents()
    grab(d, "09b_materials.png")
    d.close()

    t = TablesDialog(win.project, win)
    t.tabs.setCurrentIndex(2)
    t.resize(1150, 620)
    t.show()
    app.processEvents()
    grab(t, "10_tables.png")
    t.close()

    r = ResultsDialog(win.project, win.static_results, None, win.results_scenario, win)
    r.resize(1050, 640)
    r.tabs.setCurrentIndex(1)
    r.show()
    app.processEvents()
    grab(r, "11_results.png")
    r.close()

    win.viewport.set_view("top")
    win.viewport.fit()
    app.processEvents()
    grab(win, "12_top_view.png")
    app.quit()


QTimer.singleShot(700, do_shots)
app.exec()
print("done")
