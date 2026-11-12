"""Main application window (model generation UI)."""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QStackedWidget,
                               QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import dialogs, icons, opsgen, theme
from .model import (Element, LoadCase, LoadCombination, Material, NodalLoad,
                    Node, Project, Section, default_project, fmt)
from .ribbon import Ribbon
from .results import ResultsDialog
from .tables import TablesDialog
from .units import FORCE_UNITS, LENGTH_UNITS, UNITS
from .viewport import Viewport

APP_NAME = "OpenSees Studio"
PROJECT_FILTER = "OpenSees Studio project (*.ospj);;JSON files (*.json);;All files (*)"


# --------------------------------------------------------------------------- #
# undo / redo
# --------------------------------------------------------------------------- #
class History:
    def __init__(self, project: Project) -> None:
        self._states = [project.to_dict()]
        self._labels = ["Open project"]
        self._index = 0

    def push(self, project: Project, label: str) -> None:
        del self._states[self._index + 1:]
        del self._labels[self._index + 1:]
        self._states.append(project.to_dict())
        self._labels.append(label)
        self._index += 1
        if len(self._states) > 100:
            self._states.pop(0)
            self._labels.pop(0)
            self._index -= 1

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def undo_label(self) -> str:
        return self._labels[self._index] if self._index >= 0 else ""

    def redo_label(self) -> str:
        return self._labels[self._index + 1] if self.can_redo() else ""

    def undo(self) -> Optional[Project]:
        if not self.can_undo():
            return None
        self._index -= 1
        return Project.from_dict(self._states[self._index])

    def redo(self) -> Optional[Project]:
        if not self.can_redo():
            return None
        self._index += 1
        return Project.from_dict(self._states[self._index])


# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project = default_project()
        UNITS.set(self.project.settings.get("force_unit", "kN"),
                  self.project.settings.get("length_unit", "mm"))
        self.history = History(self.project)
        self.static_results: Optional[opsgen.StaticResults] = None
        self.modal_results: Optional[opsgen.ModalResults] = None
        self.results_scenario = ""
        self.model_locked = False

        self.setWindowTitle(f"{APP_NAME} - Untitled")
        self.resize(1480, 940)
        self.setMinimumSize(1080, 700)

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)
        self.viewport.selectionChanged.connect(self._on_selection)
        self.viewport.statusMessage.connect(self._status)

        self._make_actions()
        self._make_ribbon()
        self._make_quick_toolbars()
        self._make_docks()
        self._make_statusbar()

        self.viewport.load_scenario = "DL"
        self.viewport.set_project(self.project, fit=False)
        self.refresh_all()
        self.viewport.fit()
        self._log(f"OpenSees Studio ready. Display units: {UNITS.label()}.")
        self._log("Start with Structure > New Nodes (N), then New Elements (E).")
        self._log("Use the ribbon tabs above the viewport to create, load and analyse.")
        self._shown = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            QTimer.singleShot(0, self.viewport.fit)
            QTimer.singleShot(0, lambda: self.resizeDocks(
                [self.log_dock], [140], Qt.Vertical))

    # ================================================================== actions
    def _act(self, text: str, icon_name: str, slot, shortcut: str = "", tip: str = "",
             checkable: bool = False) -> QAction:
        a = QAction(icons.icon(icon_name), text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
        a.setToolTip(tip or text)
        a.setCheckable(checkable)
        return a

    def _make_actions(self) -> None:
        self.a_new = self._act("New", "new", self.file_new, "Ctrl+N", "New project")
        self.a_open = self._act("Open", "open", self.file_open, "Ctrl+O", "Open a project")
        self.a_save = self._act("Save", "save", self.file_save, "Ctrl+S", "Save the project")
        self.a_save_as = self._act("Save As", "save_as", self.file_save_as, "Ctrl+Shift+S")
        self.a_export_tcl = self._act("Export Tcl", "export", self.export_tcl, "",
                                      "Write an OpenSees Tcl input file")
        self.a_example = self._act("Example Frame", "example", self.load_example, "",
                                   "Load the built-in three-storey steel frame")
        self.a_exit = self._act("Exit", "exit", self.close, "Alt+F4")

        self.a_undo = self._act("Undo", "undo", self.undo, "Ctrl+Z")
        self.a_redo = self._act("Redo", "redo", self.redo, "Ctrl+Y")
        self.a_delete = self._act("Delete", "delete", self.delete_selection, "Del",
                                  "Delete the selected nodes and elements")
        self.a_sel_all = self._act("Select All", "select_all", self.viewport.select_all, "Ctrl+A")
        self.a_deselect = self._act("Deselect", "deselect", self._escape, "Esc")

        self.a_fit = self._act("Fit", "fit", self.viewport.fit, "F", "Zoom to the whole model")
        self.a_iso = self._act("Iso", "iso", lambda: self.viewport.set_view("iso"), "Ctrl+1")
        self.a_top = self._act("Top", "top", lambda: self.viewport.set_view("top"), "Ctrl+2")
        self.a_front = self._act("Front", "front", lambda: self.viewport.set_view("front"), "Ctrl+3")
        self.a_right = self._act("Right", "right", lambda: self.viewport.set_view("right"), "Ctrl+4")
        self.a_fit_sel = self._act("Fit selection", "fit_selection", self.viewport.fit_selection, "")

        self.a_nodes = self._act("New Nodes", "node", self.new_nodes, "N",
                                 "Create nodes by coordinates")
        self.a_elements = self._act("New Elements", "element", self.new_elements, "E",
                                    "Create elements between nodes")
        self.a_copy = self._act("Copy / Move", "copy", self.copy_move, "C")
        self.a_mirror = self._act("Mirror", "mirror", self.mirror, "M")
        self.a_support = self._act("Supports", "support", self.assign_supports, "S")
        self.a_material = self._act("Materials", "material", self.materials, "")
        self.a_section = self._act("Sections", "section", self.sections, "")
        self.a_tables = self._act("Tables", "tables", lambda: self.open_tables(0), "T")

        self.a_cases = self._act("Load Cases", "case", self.load_cases, "")
        self.a_nload = self._act("Nodal Loads", "nodal_load", self.nodal_loads, "L")
        self.a_eload = self._act("Element Loads", "element_load", self.element_loads, "")
        self.a_sw = self._act("Self Weight", "self_weight", self.self_weight, "")
        self.a_combo = self._act("Combinations", "combo", self.combinations, "K")

        self.a_settings = self._act("Settings", "settings", self.analysis_settings, "")
        self.a_check = self._act("Check Model", "check", self.check_model, "F9",
                                 "Validate the model before analysis")
        self.a_run = self._act("Run Static", "run_static", self.run_static, "F5",
                               "Run a static analysis for the active load case")
        self.a_modal = self._act("Modal", "modal", self.run_modal, "F6",
                                 "Run an eigenvalue analysis")
        self.a_results = self._act("Results", "results", self.show_results, "F7")
        self.a_animate = self._act("Animate", "animate", self.animate_mode, "F8", checkable=True)

        self.a_orbit = self._act("Orbit", "rotate", self._toggle_orbit, "O",
                                 "3D orbit: left-drag rotates the model "
                                 "(Shift+left or Shift+middle always orbits)", checkable=True)
        self.a_labels = self._act("Labels", "label", lambda on: self._toggle(labels=on),
                                  "", checkable=True)
        self.a_grid = self._act("Grid", "grid", lambda on: self._toggle(grid=on),
                                "", checkable=True)
        self.a_grid.setChecked(True)
        self.a_deformed = self._act("Deformed", "deformed",
                                    lambda on: self._toggle(deformed=on), "", checkable=True)
        self.a_deformed.setChecked(True)
        self.a_clean_view = self._act("Clean View", "clean", self.clean_view, "",
                                      "Hide deformation, loads and labels")
        self.a_extruded = self._act("Extruded", "extruded",
                                    lambda on: self._toggle(extruded=on), "",
                                    "Show beams and columns with full section sizes",
                                    checkable=True)
        self.a_loads_visible = self._act("Show Loads", "load_show",
                                         lambda on: self._toggle(loads=on), "",
                                         "Draw nodal and element loads in the viewport",
                                         checkable=True)
        self.a_loads_visible.setChecked(True)
        self.a_supports_visible = self._act("Show Supports", "support_show",
                                            lambda on: self._toggle(supports=on), "",
                                            "Draw support symbols in the viewport",
                                            checkable=True)
        self.a_supports_visible.setChecked(True)
        self.a_lock = self._act("Lock", "unlock", self._toggle_lock, "Ctrl+L",
                                "Lock model editing to protect analysis results",
                                checkable=True)
        self.a_model_visible = self._act("Model", "panel_model",
                                         lambda on: self.model_dock.setVisible(on), "",
                                         "Show or hide the model tree", checkable=True)
        self.a_model_visible.setChecked(True)
        self.a_props_visible = self._act("Properties", "panel_props",
                                         lambda on: self.props_dock.setVisible(on), "",
                                         "Show or hide the properties panel", checkable=True)
        self.a_props_visible.setChecked(True)
        self.a_log_visible = self._act("Messages", "panel_log",
                                       lambda on: self.log_dock.setVisible(on), "",
                                       "Show or hide the messages panel", checkable=True)
        self.a_log_visible.setChecked(True)
        self.a_quick = self._act("Quick Start", "help", self.quick_start, "F1")
        self.a_about = self._act("About", "about", self.about, "")

        self.edit_actions = (self.a_nodes, self.a_elements, self.a_copy, self.a_mirror,
                             self.a_support, self.a_material, self.a_section, self.a_tables,
                             self.a_cases, self.a_nload, self.a_eload, self.a_sw,
                             self.a_combo, self.a_delete, self.a_undo, self.a_redo,
                             self.a_settings)

    def _toggle(self, labels=None, grid=None, deformed=None, loads=None, supports=None,
                extruded=None) -> None:
        kw = {}
        if labels is not None:
            kw["show_labels"] = labels
        if grid is not None:
            kw["show_grid"] = grid
        if deformed is not None:
            kw["show_deformed"] = deformed
        if loads is not None:
            kw["show_loads"] = loads
        if supports is not None:
            kw["show_supports"] = supports
        if extruded is not None:
            kw["show_extruded"] = extruded
        self.viewport.set_show(**kw)

    def clean_view(self) -> None:
        self.viewport.stop_animation()
        self.viewport.set_show(show_deformed=False, show_loads=False,
                               show_labels=False)
        for action, state in ((self.a_deformed, False),
                              (self.a_loads_visible, False),
                              (self.a_labels, False),
                              (self.a_animate, False)):
            action.blockSignals(True)
            action.setChecked(state)
            action.blockSignals(False)
        self._status("Clean view: deformation, loads and labels hidden")

    def _toggle_orbit(self, checked: bool) -> None:
        self.viewport.set_orbit_mode(bool(checked))

    def _escape(self) -> None:
        if self.viewport.orbit_mode:
            self.a_orbit.setChecked(False)
            self.viewport.set_orbit_mode(False)
            return
        self.viewport.clear_selection()

    def _toggle_lock(self, checked: bool) -> None:
        self._set_locked(bool(checked))

    def _set_locked(self, locked: bool, message: str = "") -> None:
        locked = bool(locked)
        changed = locked != self.model_locked
        self.model_locked = locked
        self.a_lock.blockSignals(True)
        self.a_lock.setChecked(locked)
        self.a_lock.blockSignals(False)
        self.a_lock.setText("Unlock" if locked else "Lock")
        self.a_lock.setIcon(icons.icon("lock" if locked else "unlock"))
        self.a_lock.setToolTip("Model is locked. Click or press Ctrl+L to unlock and edit."
                               if locked else
                               "Lock the model to protect analysis results (Ctrl+L).")
        for action in self.edit_actions:
            action.setEnabled(not locked)
        for widget in (self.nd_x, self.nd_y, self.nd_z, *self.nd_boxes, self.nd_apply,
                       self.el_mat, self.el_sec, self.el_vx, self.el_vy, self.el_vz,
                       self.el_apply):
            widget.setEnabled(not locked)
        if hasattr(self, "lock_label"):
            self.lock_label.setVisible(locked)
        if message:
            self._status(message)
        if changed:
            self._log("Model locked - editing disabled. Press Ctrl+L to unlock."
                      if locked else
                      "Model unlocked - editing enabled. Results clear on the next change.")

    def _set_deform_scale(self, value: float) -> None:
        self.viewport.deformed_scale = float(value) if value > 0 else None
        self.viewport.update()

    def _apply_scale(self) -> None:
        value = self.scale_spin.value()
        self.viewport.deformed_scale = float(value) if value > 0 else None

    # ==================================================================== ribbon
    def _make_ribbon(self) -> None:
        ribbon = Ribbon(self)
        self.ribbon = ribbon
        self.setMenuWidget(ribbon)

        menu = ribbon.app_menu
        menu.addAction(self.a_new)
        menu.addAction(self.a_open)
        menu.addSeparator()
        menu.addAction(self.a_save)
        menu.addAction(self.a_save_as)
        menu.addSeparator()
        menu.addAction(self.a_export_tcl)
        menu.addAction(self.a_example)
        menu.addSeparator()
        menu.addAction(self.a_exit)
        ribbon.set_app_icon(icons.icon("menu", 22))
        ribbon.add_quick(self.a_undo)
        ribbon.add_quick(self.a_redo)

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0, 100000)
        self.scale_spin.setDecimals(0)
        self.scale_spin.setSingleStep(100)
        self.scale_spin.setValue(0)
        self.scale_spin.setSpecialValueText("Auto")
        self.scale_spin.setFixedWidth(88)
        self.scale_spin.setToolTip("Deformed-shape scale; Auto fits the view")
        self.scale_spin.valueChanged.connect(self._set_deform_scale)

        page = ribbon.add_tab("View")
        group = page.add_group("Navigate")
        for action in (self.a_fit, self.a_iso, self.a_top, self.a_front, self.a_right):
            group.add_large(action)
        group = page.add_group("Display")
        group.add_column((self.a_orbit, self.a_labels, self.a_grid, self.a_deformed))
        group = page.add_group("Deformed shape")
        group.add_field("Scale", self.scale_spin)
        group = page.add_group("View mode")
        group.add_large(self.a_extruded)
        group.add_large(self.a_clean_view)
        group = page.add_group("Selection")
        group.add_column((self.a_sel_all, self.a_deselect, self.a_delete))
        group = page.add_group("Panels")
        group.add_column((self.a_model_visible, self.a_props_visible, self.a_log_visible))

        page = ribbon.add_tab("Structure")
        group = page.add_group("Model")
        group.add_large(self.a_nodes)
        group.add_large(self.a_elements)
        group = page.add_group("Edit")
        group.add_large(self.a_copy)
        group.add_large(self.a_mirror)
        group = page.add_group("Selection")
        group.add_column((self.a_sel_all, self.a_deselect, self.a_delete))
        group = page.add_group("Model data")
        group.add_large(self.a_tables)

        page = ribbon.add_tab("Node/Element")
        group = page.add_group("Nodes")
        group.add_large(self.a_nodes)
        group.add_column((self.a_sel_all, self.a_deselect))
        group = page.add_group("Elements")
        group.add_large(self.a_elements)
        group.add_column((self.a_delete, self.a_fit_sel))
        group = page.add_group("Modify")
        group.add_large(self.a_copy)
        group.add_large(self.a_mirror)
        group = page.add_group("Model data")
        group.add_large(self.a_tables)

        page = ribbon.add_tab("Properties")
        group = page.add_group("Libraries")
        group.add_large(self.a_material)
        group.add_large(self.a_section)
        group = page.add_group("Model data")
        group.add_large(self.a_tables)
        group = page.add_group("Display")
        group.add_column((self.a_labels, self.a_grid))

        page = ribbon.add_tab("Boundary")
        group = page.add_group("Supports")
        group.add_large(self.a_support)
        group = page.add_group("Display")
        group.add_column((self.a_supports_visible, self.a_labels))
        group = page.add_group("Selection")
        group.add_column((self.a_sel_all, self.a_deselect))
        group = page.add_group("Model data")
        group.add_large(self.a_tables)

        page = ribbon.add_tab("Load")
        group = page.add_group("Load cases")
        group.add_large(self.a_cases)
        group.add_large(self.a_combo)
        group = page.add_group("Structural loads")
        group.add_large(self.a_nload)
        group.add_large(self.a_eload)
        group.add_large(self.a_sw)
        group = page.add_group("Display")
        group.add_column((self.a_loads_visible, self.a_labels, self.a_supports_visible))
        group = page.add_group("Model data")
        group.add_large(self.a_tables)

        page = ribbon.add_tab("Analysis")
        group = page.add_group("Analysis")
        group.add_large(self.a_settings)
        group.add_large(self.a_check)
        group.add_large(self.a_run)
        group.add_large(self.a_modal)
        group = page.add_group("Results")
        group.add_large(self.a_results)
        group.add_column((self.a_animate, self.a_deformed))
        group = page.add_group("Model state")
        group.add_large(self.a_lock)

        page = ribbon.add_tab("Results")
        group = page.add_group("Results")
        group.add_large(self.a_results)
        group.add_large(self.a_animate)
        group = page.add_group("Display")
        group.add_column((self.a_deformed, self.a_labels, self.a_grid))
        group = page.add_group("Model state")
        group.add_large(self.a_lock)

        page = ribbon.add_tab("Tools")
        group = page.add_group("Project")
        group.add_large(self.a_new)
        group.add_large(self.a_open)
        group.add_large(self.a_save)
        group = page.add_group("Exchange")
        group.add_large(self.a_export_tcl)
        group.add_large(self.a_example)
        group = page.add_group("Help")
        group.add_large(self.a_quick)
        group.add_large(self.a_about)

        ribbon.set_current("Structure")

    def _make_quick_toolbars(self) -> None:
        """Tiny horizontal command strip and vertical view strip."""
        quick = QToolBar("Quick access", self)
        quick.setObjectName("quick_toolbar")
        quick.setMovable(False)
        quick.setFloatable(False)
        quick.setContextMenuPolicy(Qt.PreventContextMenu)
        quick.setToolButtonStyle(Qt.ToolButtonIconOnly)
        quick.setIconSize(QSize(16, 16))
        for action in (self.a_save, None, self.a_run, self.a_modal, self.a_results,
                       self.a_check, None, self.a_lock, None, self.a_undo, self.a_redo):
            if action is None:
                quick.addSeparator()
            else:
                quick.addAction(action)
        self.addToolBar(Qt.TopToolBarArea, quick)
        self.quick_toolbar = quick

        views = QToolBar("Quick views", self)
        views.setObjectName("quickview_toolbar")
        views.setMovable(False)
        views.setFloatable(False)
        views.setContextMenuPolicy(Qt.PreventContextMenu)
        views.setToolButtonStyle(Qt.ToolButtonIconOnly)
        views.setIconSize(QSize(18, 18))
        for action in (self.a_fit, self.a_iso, self.a_top, self.a_front, self.a_right,
                       None, self.a_orbit, self.a_labels, self.a_grid, self.a_deformed,
                       self.a_extruded, None, self.a_fit_sel):
            if action is None:
                views.addSeparator()
            else:
                views.addAction(action)
        views.setFixedWidth(38)
        self.addToolBar(Qt.RightToolBarArea, views)
        self.quick_view_toolbar = views

    def _scenario_changed(self, text: str) -> None:
        if not text:
            return
        self.viewport.load_scenario = text
        self.project.settings["last_case"] = text
        self.viewport.update()

    # ==================================================================== docks
    def _make_docks(self) -> None:
        # ---- model tree ------------------------------------------------
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setMinimumWidth(220)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.itemDoubleClicked.connect(self._tree_double)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        dock = QDockWidget("Model", self)
        dock.setObjectName("model_dock")
        dock.setWidget(self.tree)
        dock.setMinimumWidth(230)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.model_dock = dock

        # ---- properties ------------------------------------------------
        self.props = QStackedWidget()
        self.props.setMinimumWidth(280)
        self._build_props()
        dock2 = QDockWidget("Properties", self)
        dock2.setObjectName("props_dock")
        dock2.setWidget(self.props)
        dock2.setMinimumWidth(290)
        self.addDockWidget(Qt.RightDockWidgetArea, dock2)
        self.props_dock = dock2

        # ---- messages --------------------------------------------------
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setStyleSheet(
            "font-family: Consolas; font-size: 11px; background:#fbfcfe; border:none;")
        dock3 = QDockWidget("Messages", self)
        dock3.setObjectName("log_dock")
        dock3.setWidget(self.log_view)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock3)
        dock3.setMaximumHeight(220)
        self.log_dock = dock3

        for dock, action in ((self.model_dock, self.a_model_visible),
                             (self.props_dock, self.a_props_visible),
                             (self.log_dock, self.a_log_visible)):
            dock.visibilityChanged.connect(action.setChecked)

    def _build_props(self) -> None:
        # page 0: overview
        page0 = QWidget()
        lay0 = QVBoxLayout(page0)
        lay0.setContentsMargins(10, 10, 10, 10)
        self.ov_title = QLabel("Model overview")
        self.ov_title.setStyleSheet(f"font-weight:600; color:{theme.ACCENT_DARK}; font-size:13px;")
        lay0.addWidget(self.ov_title)
        self.ov_text = QLabel()
        self.ov_text.setWordWrap(True)
        self.ov_text.setAlignment(Qt.AlignTop)
        self.ov_text.setStyleSheet(f"color:{theme.TEXT};")
        lay0.addWidget(self.ov_text)
        lay0.addSpacing(8)
        tips = QLabel(
            "<b>Quick workflow</b><br>"
            "1. <b>N</b> create nodes<br>"
            "2. <b>E</b> create elements<br>"
            "3. <b>C</b> copy / move, <b>M</b> mirror<br>"
            "4. <b>S</b> assign supports<br>"
            "5. <b>L</b> apply nodal loads<br>"
            "6. <b>K</b> build load combinations<br>"
            "7. <b>F5</b> run static analysis<br>"
            "8. <b>F7</b> review results")
        tips.setWordWrap(True)
        tips.setStyleSheet(
            f"background:#f4f8fc; border:1px solid {theme.BORDER}; border-radius:5px;"
            "padding:9px; line-height:150%;")
        lay0.addWidget(tips)
        lay0.addStretch(1)
        self.props.addWidget(page0)

        # page 1: node
        page1 = QWidget()
        lay1 = QVBoxLayout(page1)
        lay1.setContentsMargins(10, 10, 10, 10)
        self.nd_title = QLabel("Node")
        self.nd_title.setStyleSheet(f"font-weight:600; color:{theme.ACCENT_DARK}; font-size:13px;")
        lay1.addWidget(self.nd_title)
        form = QFormLayout()
        self.nd_x = dialogs.spin(0, -1e9, 1e9, UNITS.length_decimals,
                                 UNITS.length(100.0), UNITS.length_unit)
        self.nd_y = dialogs.spin(0, -1e9, 1e9, UNITS.length_decimals,
                                 UNITS.length(100.0), UNITS.length_unit)
        self.nd_z = dialogs.spin(0, -1e9, 1e9, UNITS.length_decimals,
                                 UNITS.length(100.0), UNITS.length_unit)
        form.addRow("X", self.nd_x); form.addRow("Y", self.nd_y); form.addRow("Z", self.nd_z)
        lay1.addLayout(form)
        lay1.addWidget(QLabel("Support"))
        sup = QHBoxLayout()
        self.nd_boxes: List[QCheckBox] = []
        for name in ("DX", "DY", "DZ", "RX", "RY", "RZ"):
            cb = QCheckBox(name)
            self.nd_boxes.append(cb)
            sup.addWidget(cb)
        lay1.addLayout(sup)
        self.nd_apply = QPushButton("Apply to node")
        self.nd_apply.setDefault(True)
        self.nd_apply.clicked.connect(self._apply_node_props)
        lay1.addWidget(self.nd_apply)
        lay1.addWidget(QLabel("Tip: drag in the viewport to box-select.\n"
                              "Ctrl / Shift adds to the selection."))
        lay1.addStretch(1)
        self.props.addWidget(page1)

        # page 2: element
        page2 = QWidget()
        lay2 = QVBoxLayout(page2)
        lay2.setContentsMargins(10, 10, 10, 10)
        self.el_title = QLabel("Element")
        self.el_title.setStyleSheet(f"font-weight:600; color:{theme.ACCENT_DARK}; font-size:13px;")
        lay2.addWidget(self.el_title)
        self.el_info = QLabel()
        self.el_info.setWordWrap(True)
        lay2.addWidget(self.el_info)
        form2 = QFormLayout()
        self.el_mat = QComboBox()
        self.el_sec = QComboBox()
        form2.addRow("Material", self.el_mat)
        form2.addRow("Section", self.el_sec)
        lay2.addLayout(form2)
        lay2.addWidget(QLabel("Local z axis (vecxz)"))
        row = QHBoxLayout()
        self.el_vx = dialogs.spin(0, -1, 1, 3, 0.1)
        self.el_vy = dialogs.spin(0, -1, 1, 3, 0.1)
        self.el_vz = dialogs.spin(1, -1, 1, 3, 0.1)
        row.addWidget(self.el_vx); row.addWidget(self.el_vy); row.addWidget(self.el_vz)
        lay2.addLayout(row)
        self.el_apply = QPushButton("Apply to element")
        self.el_apply.clicked.connect(self._apply_element_props)
        lay2.addWidget(self.el_apply)
        lay2.addStretch(1)
        self.props.addWidget(page2)

    def _make_statusbar(self) -> None:
        sb = self.statusBar()
        self.status_label = QLabel("Ready")
        sb.addWidget(self.status_label, 1)
        self.lock_label = QLabel("MODEL LOCKED")
        self.lock_label.setStyleSheet(
            "color:#b45309; font-weight:700; padding:0 10px;")
        self.lock_label.setVisible(False)
        sb.addPermanentWidget(self.lock_label)
        self.model_label = QLabel("")
        sb.addPermanentWidget(self.model_label)

        case_label = QLabel("Load case")
        case_label.setStyleSheet(f"color:{theme.MUTED}; padding-left:10px;")
        sb.addPermanentWidget(case_label)
        self.scenario_combo = QComboBox()
        self.scenario_combo.setMinimumWidth(150)
        self.scenario_combo.setMaximumWidth(210)
        self.scenario_combo.currentTextChanged.connect(self._scenario_changed)
        sb.addPermanentWidget(self.scenario_combo)

        def unit_label(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setStyleSheet(f"color:{theme.MUTED}; padding-left:10px;")
            return lab

        self.units_force = QComboBox()
        self.units_force.addItems(FORCE_UNITS)
        self.units_force.setCurrentText(UNITS.force_unit)
        self.units_force.setFixedWidth(74)
        self.units_force.setFocusPolicy(Qt.NoFocus)
        self.units_force.setToolTip("Force units used for input and results "
                                    "(model data stays in kN)")
        self.units_length = QComboBox()
        self.units_length.addItems(LENGTH_UNITS)
        self.units_length.setCurrentText(UNITS.length_unit)
        self.units_length.setFixedWidth(74)
        self.units_length.setFocusPolicy(Qt.NoFocus)
        self.units_length.setToolTip("Length units used for input and results "
                                     "(model data stays in mm)")

        sb.addPermanentWidget(unit_label("Force"))
        sb.addPermanentWidget(self.units_force)
        sb.addPermanentWidget(unit_label("Length"))
        sb.addPermanentWidget(self.units_length)

        self.units_force.currentTextChanged.connect(self._units_changed)
        self.units_length.currentTextChanged.connect(self._units_changed)

    def _sync_units(self) -> None:
        """Adopt the display units stored in the current project."""
        UNITS.set(str(self.project.settings.get("force_unit", "kN")),
                  str(self.project.settings.get("length_unit", "mm")))
        self.project.settings["force_unit"] = UNITS.force_name
        self.project.settings["length_unit"] = UNITS.length_name
        for combo, value in ((self.units_force, UNITS.force_name),
                             (self.units_length, UNITS.length_name)):
            combo.blockSignals(True)
            combo.setCurrentText(value)
            combo.blockSignals(False)
        self._apply_unit_labels()

    def _apply_unit_labels(self) -> None:
        for w in (self.nd_x, self.nd_y, self.nd_z):
            w.setSuffix(" " + UNITS.length_unit)
            w.setDecimals(UNITS.length_decimals)
            w.setSingleStep(UNITS.length(100.0))

    def _units_changed(self, *_args) -> None:
        self.project.settings["force_unit"] = self.units_force.currentText()
        self.project.settings["length_unit"] = self.units_length.currentText()
        UNITS.set(self.project.settings["force_unit"],
                  self.project.settings["length_unit"])
        self._apply_unit_labels()
        self._refresh_tree()
        self._on_selection()
        self.viewport.update()
        self._status(f"Display units: {UNITS.label()}")

    # ================================================================= refresh
    def refresh_all(self) -> None:
        self._sync_units()
        self._refresh_tree()
        self._refresh_scenarios()
        self._refresh_props()
        self._update_title()
        self.viewport.update()

    def _update_title(self) -> None:
        name = os.path.basename(self.project.path) if self.project.path else "Untitled"
        self.setWindowTitle(f"{APP_NAME} - {name}")
        self.model_label.setText(
            f"{len(self.project.nodes)} nodes · {len(self.project.elements)} elements · "
            f"{len(self.project.cases)} cases")

    def _refresh_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        p = self.project
        root = QTreeWidgetItem([p.title or "Model"])
        root.setData(0, Qt.UserRole, ("root", None))
        f = QFont("Segoe UI", 9, QFont.Bold)
        root.setFont(0, f)
        self.tree.addTopLevelItem(root)

        def group(title: str, key: str, count: Optional[int] = None,
                  parent=root) -> QTreeWidgetItem:
            text = title if count is None else f"{title}   ({count})"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.UserRole, (key, None))
            parent.addChild(item)
            return item

        g_nodes = group("Nodes", "nodes", len(p.nodes))
        g_elem = group("Elements", "elements", len(p.elements))

        def add_child(parent: QTreeWidgetItem, text: str, kind: str = "",
                      tag=None) -> QTreeWidgetItem:
            item = QTreeWidgetItem([text])
            if kind:
                item.setData(0, Qt.UserRole, (kind, tag))
            if kind in ("material", "section"):
                item.setToolTip(0, "Double-click: select elements using this. "
                                   "Right-click: delete.")
            parent.addChild(item)
            return item

        g_mat = group("Materials", "materials", len(p.materials))
        for m in p.materials.values():
            add_child(g_mat, f"{m.tag}   {m.name}   ({m.kind})", "material", m.tag)
        g_sec = group("Sections", "sections", len(p.sections))
        for s in p.sections.values():
            add_child(g_sec, f"{s.tag}   {s.name}   ({s.shape})", "section", s.tag)

        b = group("Boundary", "boundary")
        g_sup = group("Supports", "supports",
                      sum(1 for n in p.nodes.values() if any(n.support)), b)
        for n in p.nodes.values():
            if any(n.support):
                add_child(g_sup, f"{n.tag}   {n.support_code()}", "node", n.tag)

        ld = group("Loads", "loads")
        g_cases = group("Load Cases", "cases", len(p.cases), ld)
        for c in p.cases.values():
            add_child(g_cases, f"{c.name}   ({c.kind})", "case", c.name)
        g_nl = group("Nodal Loads", "nodal_loads", len(p.nodal_loads), ld)
        for load in p.nodal_loads[:200]:
            add_child(g_nl, f"{load.tag}   node {load.node}   {load.case}",
                      "node", load.node)
        if len(p.nodal_loads) > 200:
            add_child(g_nl, f"... {len(p.nodal_loads) - 200} more in Tables")
        g_elload = group("Element Loads", "element_loads", len(p.elem_loads), ld)
        for load in p.elem_loads[:200]:
            add_child(g_elload, f"{load.tag}   element {load.elem}   {load.case}",
                      "element", load.elem)
        if len(p.elem_loads) > 200:
            add_child(g_elload, f"... {len(p.elem_loads) - 200} more in Tables")
        g_sw = group("Self Weight", "self_weight", len(p.self_weight), ld)
        for case, factor in p.self_weight.items():
            add_child(g_sw, f"{case}   factor {fmt(factor, 3)}")

        g_combo = group("Load Combinations", "combos", len(p.combos))
        for c in p.combos.values():
            add_child(g_combo, f"{c.name}   ({c.kind})", "combo", c.name)

        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _tree_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        key, tag = data
        if tag is None:
            if key == "nodes":
                self.open_tables(0)
            elif key == "elements":
                self.open_tables(2)
            return
        if key == "node":
            self.viewport.select_nodes([tag])
        elif key == "element":
            self.viewport.select_elements([tag])

    def _tree_double(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        key, tag = data
        if tag is not None:
            if key in ("material", "section"):
                self._select_elements_using(key, tag)
            return
        if key in ("nodes", "elements"):
            return
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        actions = {
            "supports": lambda: self.open_tables(1),
            "materials": self.materials,
            "sections": self.sections,
            "cases": self.load_cases,
            "nodal_loads": lambda: self.open_tables(6),
            "element_loads": lambda: self.open_tables(7),
            "self_weight": self.self_weight,
            "combos": self.combinations,
        }
        fn = actions.get(key)
        if fn:
            fn()

    def _select_elements_using(self, kind: str, tag) -> None:
        if kind == "material":
            tags = [e.tag for e in self.project.elements.values() if e.mat == tag]
            label = f"material {tag}"
        else:
            tags = [e.tag for e in self.project.elements.values() if e.sec == tag]
            label = f"section {tag}"
        if not tags:
            self._status(f"No elements use {label}")
            return
        self.viewport.select_elements(tags)
        self.viewport.fit_selection()
        self._status(f"Selected {len(tags)} element(s) using {label}")

    def _tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data[1] is None or data[0] not in ("material", "section"):
            return
        kind, tag = data
        menu = QMenu(self)
        select = menu.addAction("Select elements using this")
        select.triggered.connect(lambda: self._select_elements_using(kind, tag))
        menu.addSeparator()
        delete = menu.addAction(f"Delete {kind} {tag}")
        delete.setEnabled(not self.model_locked)
        delete.triggered.connect(lambda: self._delete_tree_entity(kind, tag))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _delete_tree_entity(self, kind: str, tag) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        if kind == "material":
            collection = self.project.materials
            used = [e.tag for e in self.project.elements.values() if e.mat == tag]
            noun = "material"
        else:
            collection = self.project.sections
            used = [e.tag for e in self.project.elements.values() if e.sec == tag]
            noun = "section"
        obj = collection.get(tag)
        if obj is None:
            return
        if used:
            QMessageBox.warning(self, f"Delete {noun}",
                                f"{noun.capitalize()} {tag} is used by {len(used)} element(s).")
            return
        if len(collection) <= 1:
            QMessageBox.warning(self, f"Delete {noun}",
                                f"The model needs at least one {noun}.")
            return
        if QMessageBox.question(self, f"Delete {noun}",
                                f"Delete {noun} {tag} - {obj.name}?") != QMessageBox.Yes:
            return
        del collection[tag]
        self._commit(f"Deleted {noun} {tag}")

    def _refresh_scenarios(self) -> None:
        names = self.project.scenario_names()
        current = self.scenario_combo.currentText()
        preferred = current or self.project.settings.get("last_case", "")
        self.scenario_combo.blockSignals(True)
        self.scenario_combo.clear()
        self.scenario_combo.addItems(names)
        if preferred in names:
            self.scenario_combo.setCurrentText(preferred)
        elif names:
            self.scenario_combo.setCurrentIndex(0)
        self.scenario_combo.blockSignals(False)
        if self.scenario_combo.currentText():
            self.viewport.load_scenario = self.scenario_combo.currentText()

    def _refresh_props(self) -> None:
        p = self.project
        self.ov_text.setText(
            f"<table cellspacing='6'>"
            f"<tr><td>Nodes</td><td><b>{len(p.nodes)}</b></td></tr>"
            f"<tr><td>Elements</td><td><b>{len(p.elements)}</b></td></tr>"
            f"<tr><td>Materials</td><td><b>{len(p.materials)}</b></td></tr>"
            f"<tr><td>Sections</td><td><b>{len(p.sections)}</b></td></tr>"
            f"<tr><td>Supports</td><td><b>{sum(1 for n in p.nodes.values() if any(n.support))}</b></td></tr>"
            f"<tr><td>Load cases</td><td><b>{len(p.cases)}</b></td></tr>"
            f"<tr><td>Nodal loads</td><td><b>{len(p.nodal_loads)}</b></td></tr>"
            f"<tr><td>Element loads</td><td><b>{len(p.elem_loads)}</b></td></tr>"
            f"<tr><td>Combinations</td><td><b>{len(p.combos)}</b></td></tr>"
            f"</table>")
        self._on_selection()

    def _on_selection(self) -> None:
        sel_n = self.viewport.sel_nodes
        sel_e = self.viewport.sel_elements
        if len(sel_n) == 1 and not sel_e:
            tag = next(iter(sel_n))
            n = self.project.nodes.get(tag)
            if not n:
                return
            self.props.setCurrentIndex(1)
            self.nd_title.setText(f"Node {tag}")
            for w, v in ((self.nd_x, UNITS.length(n.x)),
                         (self.nd_y, UNITS.length(n.y)),
                         (self.nd_z, UNITS.length(n.z))):
                w.blockSignals(True); w.setValue(v); w.blockSignals(False)
            for cb, b in zip(self.nd_boxes, n.support):
                cb.blockSignals(True); cb.setChecked(bool(b)); cb.blockSignals(False)
        elif len(sel_e) == 1 and not sel_n:
            tag = next(iter(sel_e))
            e = self.project.elements.get(tag)
            if not e:
                return
            self.props.setCurrentIndex(2)
            self.el_title.setText(f"Element {tag}   ({e.kind})")
            sec = self.project.section_of(e)
            self.el_info.setText(
                f"Nodes {e.nodes}<br>Length {fmt(UNITS.length(self.project.element_length(e)), 1)} "
                f"{UNITS.length_unit}<br>"
                f"Section A = {fmt(UNITS.area(sec.A), 1)} {UNITS.area_unit}, "
                f"Iy = {fmt(UNITS.inertia(sec.Iy), 1)}, "
                f"Iz = {fmt(UNITS.inertia(sec.Iz), 1)} {UNITS.inertia_unit}")
            self.el_mat.clear(); self.el_sec.clear()
            for m in self.project.materials.values():
                self.el_mat.addItem(f"{m.tag}  {m.name}", m.tag)
            for s in self.project.sections.values():
                self.el_sec.addItem(f"{s.tag}  {s.name}", s.tag)
            self.el_mat.setCurrentIndex(max(0, self.el_mat.findData(e.mat)))
            self.el_sec.setCurrentIndex(max(0, self.el_sec.findData(e.sec)))
            vx = e.vecxz or opsgen.auto_vecxz(self.project.node_xyz(e.nodes[0]),
                                                   self.project.node_xyz(e.nodes[1]))
            for w, v in ((self.el_vx, vx[0]), (self.el_vy, vx[1]), (self.el_vz, vx[2])):
                w.blockSignals(True); w.setValue(v); w.blockSignals(False)
        else:
            self.props.setCurrentIndex(0)
            if sel_n or sel_e:
                self.status_label.setText(
                    f"{len(sel_n)} node(s) and {len(sel_e)} element(s) selected")

    # ==================================================================== utils
    def _log(self, text: str) -> None:
        if text:
            self.log_view.appendPlainText(text)

    def _status(self, text: str) -> None:
        self.status_label.setText(text)

    def _adopt(self, other: Project) -> None:
        p = self.project
        keep_units = (p.settings.get("force_unit", "kN"),
                      p.settings.get("length_unit", "m"))
        for attr in ("nodes", "elements", "materials", "sections", "cases",
                     "nodal_loads", "elem_loads", "self_weight", "combos",
                     "settings", "title"):
            setattr(p, attr, getattr(other, attr))
        p.settings["force_unit"], p.settings["length_unit"] = keep_units

    def _commit(self, label: str) -> None:
        if self.static_results or self.modal_results:
            self._clear_results()
        self.history.push(self.project, label)
        self.refresh_all()
        self._log(f"✔ {label}")

    def _warn(self, text: str, title: str = "OpenSees Studio") -> None:
        QMessageBox.warning(self, title, text)

    # =================================================================== file
    def load_example(self) -> None:
        from .example import demo_frame

        self.project = demo_frame()
        self.history = History(self.project)
        self.static_results = None
        self.modal_results = None
        self.viewport.set_project(self.project)
        self.refresh_all()
        self.viewport.fit()
        self.viewport.load_scenario = self.scenario_combo.currentText()
        self._set_locked(False)
        self._log("Loaded example: 3-storey steel frame (39 elements, 3 load cases).")

    def open_path(self, path: str) -> None:
        try:
            loaded = Project.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self.project = loaded
        self.history = History(self.project)
        self.static_results = None
        self.modal_results = None
        self.viewport.set_project(self.project)
        self.refresh_all()
        self.viewport.fit()
        self._set_locked(False)

    def apply_project_dict(self, data: dict, fit: bool = True) -> None:
        """Replace the current model with a project dictionary (MCP bridge)."""
        loaded = Project.from_dict(data)
        self._adopt(loaded)
        self.project.title = str(data.get("title", self.project.title))
        self._clear_results()
        self._set_locked(False)
        self.viewport.set_project(self.project, fit=fit)
        self.refresh_all()
        self._log("Model synchronised from an MCP client.")

    def bridge_show_static(self, payload: dict) -> None:
        res = opsgen.StaticResults(scenario=str(payload.get("scenario", "")))
        res.displacements = {int(k): [float(x) for x in v]
                             for k, v in (payload.get("displacements") or {}).items()}
        res.reactions = {int(k): [float(x) for x in v]
                         for k, v in (payload.get("reactions") or {}).items()}
        res.element_forces = {int(k): [float(x) for x in v]
                              for k, v in (payload.get("element_forces") or {}).items()}
        res.element_kind = {int(k): str(v) for k, v in (payload.get("element_kind") or {}).items()}
        res.max_disp = float(payload.get("max_disp", 0.0))
        self.static_results = res
        self.modal_results = None
        self.results_scenario = res.scenario
        self.viewport.load_scenario = res.scenario
        if self.scenario_combo.findText(res.scenario) >= 0:
            self.scenario_combo.setCurrentText(res.scenario)
        self.viewport.set_static_results(res)
        self.viewport.fit()
        self._apply_scale()
        self.a_deformed.setChecked(True)
        self._status(f"MCP: static results for {res.scenario}")
        self._set_locked(True)
        self.ribbon.set_current("Results")

    def bridge_show_mode(self, payload: dict) -> None:
        modes = [opsgen.ModeResult(int(m["mode"]), float(m["eigenvalue"]),
                                   float(m["omega"]), float(m["period"]),
                                   float(m["frequency"]))
                 for m in payload.get("modes", [])]
        shapes = {int(k): {int(n): [float(x) for x in v] for n, v in shape.items()}
                  for k, shape in (payload.get("shapes") or {}).items()}
        res = opsgen.ModalResults(modes=modes, shapes=shapes)
        self.modal_results = res
        self.static_results = None
        mode = int(payload.get("mode", 1))
        self.viewport.set_modal_results(res, mode)
        self.viewport.fit()
        self.viewport.start_animation()
        self.a_animate.setChecked(True)
        self._status(f"MCP: animating mode {mode}")
        self._set_locked(True)
        self.ribbon.set_current("Results")

    def file_new(self) -> None:
        if QMessageBox.question(self, "New project",
                                "Discard the current model and start a new project?") != QMessageBox.Yes:
            return
        self.project = default_project()
        self.project.settings = dict(self.project.settings)
        self.history = History(self.project)
        self.static_results = None
        self.modal_results = None
        self.viewport.set_project(self.project)
        self.refresh_all()
        self._set_locked(False)
        self._log("New project created.")

    def file_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", PROJECT_FILTER)
        if not path:
            return
        try:
            loaded = Project.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self.project = loaded
        self.history = History(self.project)
        self.static_results = None
        self.modal_results = None
        self.viewport.set_project(self.project)
        self.refresh_all()
        self.viewport.fit()
        self._set_locked(False)
        self._log(f"Opened {path}")

    def file_save(self) -> None:
        if not self.project.path:
            self.file_save_as()
            return
        try:
            self.project.save(self.project.path)
            self._log(f"Saved {self.project.path}")
            self._status("Project saved")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def file_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "model.ospj", PROJECT_FILTER)
        if not path:
            return
        if not path.lower().endswith((".ospj", ".json")):
            path += ".ospj"
        try:
            self.project.save(path)
            self._update_title()
            self._log(f"Saved {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def export_tcl(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Tcl", "model.tcl",
                                              "Tcl files (*.tcl);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(opsgen.export_tcl(self.project))
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._log(f"Tcl exported to {path}")
        QMessageBox.information(self, "Export complete",
                                f"OpenSees Tcl input written to:\n{path}")

    # ================================================================== undo
    def undo(self) -> None:
        state = self.history.undo()
        if state is None:
            self._status("Nothing to undo")
            return
        self._adopt(state)
        self._clear_results()
        self.refresh_all()
        self._status("Undo")

    def redo(self) -> None:
        state = self.history.redo()
        if state is None:
            self._status("Nothing to redo")
            return
        self._adopt(state)
        self._clear_results()
        self.refresh_all()
        self._status("Redo")

    def _clear_results(self) -> None:
        self.static_results = None
        self.modal_results = None
        self.viewport.clear_results()

    # ============================================================== structure
    def new_nodes(self) -> None:
        dlg = dialogs.NodeDialog(self.project, self)
        if not dlg.exec():
            return
        new = []
        for x, y, z in dlg.positions():
            tag = self.project.next_node()
            self.project.nodes[tag] = Node(tag, x, y, z)
            new.append(tag)
        self._commit(f"Created {len(new)} node(s)")
        self.viewport.select_nodes(new)
        self.viewport.fit()
        self._status(f"Created nodes {new[0]}…{new[-1]}" if len(new) > 1 else f"Created node {new[0]}")

    def new_elements(self) -> None:
        selected = sorted(self.viewport.sel_nodes)
        if not selected:
            self._warn("Select the nodes first (click or box-select in the viewport), "
                       "or type their tags in the dialog.")
        dlg = dialogs.ElementDialog(self.project, selected, self)
        if not dlg.exec():
            return
        spec = dlg.spec()
        tags = spec["nodes"]
        kind = spec["kind"]
        if kind == "shell":
            if len(tags) % 4 != 0 or not tags:
                self._warn("A shell element needs 4 nodes (i, j, k, l).")
                return
            groups = [tags[i:i + 4] for i in range(0, len(tags), 4)]
        else:
            if len(tags) < 2:
                self._warn("A beam or truss needs at least 2 nodes.")
                return
            groups = [[tags[i], tags[i + 1]] for i in range(len(tags) - 1)]

        for group in groups:
            for t in group:
                if t not in self.project.nodes:
                    self._warn(f"Node {t} does not exist.")
                    return
            if len(set(group)) != len(group):
                self._warn("An element cannot reuse the same node.")
                return
        if spec["mat"] not in self.project.materials:
            self._warn("Select a valid material.")
            return
        if spec["sec"] not in self.project.sections:
            self._warn("Select a valid section.")
            return

        created = []
        for group in groups:
            tag = self.project.next_element()
            e = Element(tag, kind, group, spec["mat"], spec["sec"],
                        spec["vecxz"], spec["thickness"])
            self.project.elements[tag] = e
            created.append(tag)
        self._commit(f"Created {len(created)} element(s)")
        self.viewport.select_elements(created)

    def copy_move(self) -> None:
        node_set = set(self.viewport.sel_nodes)
        for t in self.viewport.sel_elements:
            e = self.project.elements.get(t)
            if e:
                node_set.update(e.nodes)
        if not node_set and not self.viewport.sel_elements:
            self._warn("Select nodes and/or elements to copy or move.")
            return
        dlg = dialogs.CopyMoveDialog("Copy / Move", self)
        if not dlg.exec():
            return
        dx, dy, dz = dlg.delta()
        if abs(dx) + abs(dy) + abs(dz) < 1e-12:
            self._warn("Enter a non-zero translation.")
            return
        copy = dlg.is_copy()
        count = dlg.count.value() if copy else 1

        elem_set = set(self.viewport.sel_elements)
        if dlg.with_elements.isChecked() and node_set:
            for t, e in self.project.elements.items():
                if all(n in node_set for n in e.nodes):
                    elem_set.add(t)

        if not copy:
            for t in node_set:
                n = self.project.nodes.get(t)
                if n:
                    n.x += dx; n.y += dy; n.z += dz
            self._commit(f"Moved {len(node_set)} node(s)")
            self.viewport.update()
            return

        new_nodes: List[int] = []
        for k in range(1, count + 1):
            mapping: Dict[int, int] = {}
            for t in sorted(node_set):
                n = self.project.nodes.get(t)
                if n is None:
                    continue
                tag = self.project.next_node()
                self.project.nodes[tag] = Node(tag, n.x + k * dx, n.y + k * dy, n.z + k * dz)
                mapping[t] = tag
                new_nodes.append(tag)
            for t in sorted(elem_set):
                e = self.project.elements.get(t)
                if e is None or any(n not in mapping for n in e.nodes):
                    continue
                tag = self.project.next_element()
                self.project.elements[tag] = Element(
                    tag, e.kind, [mapping[n] for n in e.nodes], e.mat, e.sec,
                    list(e.vecxz) if e.vecxz else None, e.thickness, e.group)
        self._commit(f"Copied {len(node_set)} node(s) ×{count}")
        if dlg.keep_selection.isChecked():
            self.viewport.select_nodes(new_nodes)
        self._status(f"Created {len(new_nodes)} nodes")

    def mirror(self) -> None:
        node_set = set(self.viewport.sel_nodes)
        for t in self.viewport.sel_elements:
            e = self.project.elements.get(t)
            if e:
                node_set.update(e.nodes)
        if not node_set:
            self._warn("Select nodes and/or elements to mirror.")
            return
        dlg = dialogs.MirrorDialog(self)
        if not dlg.exec():
            return
        axis, copy, with_elements = dlg.spec()
        elem_set = set(self.viewport.sel_elements)
        if with_elements:
            for t, e in self.project.elements.items():
                if all(n in node_set for n in e.nodes):
                    elem_set.add(t)

        def flip(xyz):
            c = list(xyz)
            c[axis] = -c[axis]
            return c

        new_nodes = []
        if copy:
            mapping = {}
            for t in sorted(node_set):
                n = self.project.nodes.get(t)
                if n is None:
                    continue
                tag = self.project.next_node()
                x, y, z = flip((n.x, n.y, n.z))
                self.project.nodes[tag] = Node(tag, x, y, z)
                mapping[t] = tag
                new_nodes.append(tag)
            for t in sorted(elem_set):
                e = self.project.elements.get(t)
                if e is None or any(n not in mapping for n in e.nodes):
                    continue
                nodes = [mapping[n] for n in e.nodes]
                if e.kind == "shell":
                    nodes = list(reversed(nodes))
                tag = self.project.next_element()
                self.project.elements[tag] = Element(
                    tag, e.kind, nodes, e.mat, e.sec, list(e.vecxz) if e.vecxz else None, e.thickness, e.group)
            self._commit(f"Mirrored {len(node_set)} node(s)")
            self.viewport.select_nodes(new_nodes)
        else:
            for t in node_set:
                n = self.project.nodes.get(t)
                if n:
                    n.x, n.y, n.z = flip((n.x, n.y, n.z))
            for t in elem_set:
                e = self.project.elements.get(t)
                if e and e.kind == "shell":
                    e.nodes = list(reversed(e.nodes))
            self._commit(f"Mirrored {len(node_set)} node(s) in place")

    def assign_supports(self) -> None:
        if not self.project.nodes:
            self._warn("Create nodes first.")
            return
        dlg = dialogs.SupportDialog(self.project, sorted(self.viewport.sel_nodes), self)
        if not dlg.exec():
            return
        targets = dlg.target()
        support = dlg.support()
        for t in targets:
            n = self.project.nodes.get(t)
            if n:
                n.support = list(support)
        self._commit(f"Assigned supports to {len(targets)} node(s)")

    def materials(self) -> None:
        dlg = dialogs.MaterialDialog(self.project, self)
        if not dlg.exec():
            return
        missing = [e.tag for e in self.project.elements.values()
                   if e.mat not in dlg.materials]
        if missing:
            self._warn(f"Elements {missing[:8]} reference deleted materials.")
            return
        self.project.materials = dlg.materials
        self._commit("Edited materials")

    def sections(self) -> None:
        dlg = dialogs.SectionDialog(self.project, self)
        if not dlg.exec():
            return
        missing = [e.tag for e in self.project.elements.values()
                   if e.sec not in dlg.sections]
        if missing:
            self._warn(f"Elements {missing[:8]} reference deleted sections.")
            return
        self.project.sections = dlg.sections
        self._commit("Edited sections")

    # =================================================================== loads
    def load_cases(self) -> None:
        dlg = dialogs.LoadCaseDialog(self.project, self)
        if not dlg.exec():
            return
        cases = dlg.collect()
        if not cases:
            self._warn("At least one load case is required.")
            return
        mapping = dlg.rename_map

        def remap(name: str) -> str:
            return mapping.get(name, name)

        for nl in self.project.nodal_loads:
            nl.case = remap(nl.case)
        for el in self.project.elem_loads:
            el.case = remap(el.case)
        sw = {remap(k): v for k, v in self.project.self_weight.items()}
        self.project.self_weight = {k: v for k, v in sw.items() if k in cases}
        for combo in self.project.combos.values():
            combo.factors = [(remap(c), f) for c, f in combo.factors if remap(c) in cases]

        self.project.cases = cases
        self.project.nodal_loads = [l for l in self.project.nodal_loads if l.case in cases]
        self.project.elem_loads = [l for l in self.project.elem_loads if l.case in cases]
        self._commit("Edited load cases")

    def nodal_loads(self) -> None:
        if not self.project.nodes:
            self._warn("Create nodes first.")
            return
        dlg = dialogs.NodalLoadDialog(self.project, sorted(self.viewport.sel_nodes), self)
        if not dlg.exec():
            return
        targets = dlg.target()
        if not targets:
            self._warn("Select at least one target node.")
            return
        case = dlg.case.currentText()
        values = dlg.values()
        if dlg.replace.isChecked():
            self.project.nodal_loads = [
                l for l in self.project.nodal_loads
                if not (l.node in targets and l.case == case)]
        for t in targets:
            tag = self.project.next_load()
            self.project.nodal_loads.append(NodalLoad(tag, t, case, list(values)))
        self._commit(f"Applied nodal load to {len(targets)} node(s) [{case}]")

    def element_loads(self) -> None:
        if not self.project.elements:
            self._warn("Create elements first.")
            return
        dlg = dialogs.ElementLoadDialog(self.project, sorted(self.viewport.sel_elements), self)
        if not dlg.exec():
            return
        targets = dlg.target()
        if not targets:
            self._warn("Select at least one target element.")
            return
        case = dlg.case.currentText()
        spec = dlg.spec()
        if dlg.replace.isChecked():
            self.project.elem_loads = [
                l for l in self.project.elem_loads
                if not (l.elem in targets and l.case == case)]
        from .model import ElementLoad
        for t in targets:
            tag = self.project.next_load()
            self.project.elem_loads.append(ElementLoad(
                tag, t, case, spec["kind"], spec["direction"], spec["value"],
                spec["value2"], spec["position"], spec["trapezoid"]))
        self._commit(f"Applied element load to {len(targets)} element(s) [{case}]")

    def self_weight(self) -> None:
        dlg = dialogs.SelfWeightDialog(self.project, self)
        if not dlg.exec():
            return
        case = dlg.case.currentText()
        factor = dlg.factor.value()
        if abs(factor) < 1e-12:
            self.project.self_weight.pop(case, None)
        else:
            self.project.self_weight[case] = factor
        self._commit(f"Self weight factor {fmt(factor, 3)} on {case}")

    def combinations(self) -> None:
        dlg = dialogs.ComboDialog(self.project, self)
        if not dlg.exec():
            return
        self.project.combos = dlg.combos
        self._commit("Edited load combinations")

    # ================================================================ analysis
    def analysis_settings(self) -> None:
        dlg = dialogs.AnalysisDialog(self.project, self)
        if not dlg.exec():
            return
        self.project.settings.update(dlg.values())
        self._commit("Analysis settings")

    def check_model(self) -> None:
        errors, warnings = opsgen.check_model(self.project)
        for line in errors:
            self._log(f"✖ {line}")
        for line in warnings:
            self._log(f"⚠ {line}")
        if not errors and not warnings:
            QMessageBox.information(self, "Model check",
                                    "Model check passed - no issues found.")
            return
        body = ""
        if errors:
            body += "<b>Errors</b><ul>" + "".join(f"<li>{e}</li>" for e in errors) + "</ul>"
        if warnings:
            body += "<b>Warnings</b><ul>" + "".join(f"<li>{w}</li>" for w in warnings) + "</ul>"
        QMessageBox.warning(self, "Model check", body)

    def _scenario(self) -> str:
        text = self.scenario_combo.currentText()
        if not text:
            self._warn("Create a load case first.")
        return text

    def run_static(self) -> None:
        scenario = self._scenario()
        if not scenario:
            return
        if not self.project.elements:
            self._warn("The model has no elements.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = opsgen.run_static(self.project, scenario)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Analysis failed", str(exc))
            self._log(f"✖ Static analysis failed: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.static_results = res
        self.modal_results = None
        self.results_scenario = scenario
        self.viewport.load_scenario = scenario
        self.viewport.set_static_results(res)
        self._apply_scale()
        self._log(f"Static analysis '{scenario}' complete. Max |u| = "
                  f"{fmt(UNITS.length(res.max_disp), 4)} {UNITS.length_unit}")
        self._status(f"Static analysis complete - max displacement "
                     f"{fmt(UNITS.length(res.max_disp), 4)} {UNITS.length_unit}")
        self.a_animate.setChecked(False)
        self._set_locked(True)
        self.ribbon.set_current("Results")
        self._log("Model locked after analysis. Press Ctrl+L to unlock before editing.")

    def run_modal(self) -> None:
        if not self.project.elements:
            self._warn("The model has no elements.")
            return
        nmodes = int(self.project.settings.get("modal_modes", 6))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = opsgen.run_modal(self.project, nmodes)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Modal analysis failed", str(exc))
            self._log(f"✖ Modal analysis failed: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.modal_results = res
        self.static_results = None
        self.viewport.set_modal_results(res, 1)
        txt = ", ".join(f"T{m.mode}={fmt(m.period, 4)}s" for m in res.modes[:4])
        self._log(f"Modal analysis complete: {txt}")
        self._status(f"Modal analysis complete - {len(res.modes)} modes")
        self._set_locked(True)
        self.ribbon.set_current("Results")
        self._log("Model locked after analysis. Press Ctrl+L to unlock before editing.")

    def _show_results_dialog(self) -> None:
        if not self.static_results and not self.modal_results:
            self._warn("Run an analysis first (F5 static, F6 modal).")
            return
        dlg = ResultsDialog(self.project, self.static_results, self.modal_results,
                            self.results_scenario, self)
        dlg.plotStatic.connect(self._plot_static)
        dlg.plotMode.connect(self._plot_mode)
        dlg.exec()

    def show_results(self) -> None:
        self._show_results_dialog()

    def _plot_static(self, scenario: str) -> None:
        self.viewport.load_scenario = scenario
        self.viewport.set_static_results(self.static_results)
        self._apply_scale()
        self.viewport.show_deformed = True
        self.a_deformed.setChecked(True)
        self.viewport.fit()

    def _plot_mode(self, mode: int) -> None:
        if not self.modal_results:
            return
        self.viewport.set_modal_results(self.modal_results, mode)
        self.viewport.show_deformed = True
        self.a_deformed.setChecked(True)
        self.viewport.start_animation()
        self.a_animate.setChecked(True)
        self._status(f"Animating mode {mode}")

    def animate_mode(self) -> None:
        if self.a_animate.isChecked():
            if not self.modal_results:
                self.a_animate.setChecked(False)
                self._warn("Run a modal analysis first (F6).")
                return
            self.viewport.start_animation()
        else:
            self.viewport.stop_animation()

    def delete_selection(self) -> None:
        nodes = set(self.viewport.sel_nodes)
        elems = set(self.viewport.sel_elements)
        if not nodes and not elems:
            self._status("Nothing selected")
            return
        for t in elems:
            self.project.elements.pop(t, None)
        removed_el = [t for t, e in self.project.elements.items()
                      if any(n in nodes for n in e.nodes)]
        for t in removed_el:
            self.project.elements.pop(t, None)
        for t in nodes:
            self.project.nodes.pop(t, None)
        self.project.nodal_loads = [l for l in self.project.nodal_loads if l.node in self.project.nodes]
        self.project.elem_loads = [l for l in self.project.elem_loads if l.elem in self.project.elements]
        self.viewport.clear_selection()
        self._clear_results()
        self._commit(f"Deleted {len(nodes)} node(s), {len(elems) + len(removed_el)} element(s)")

    # ================================================================== props
    def _apply_node_props(self) -> None:
        sel = self.viewport.sel_nodes
        if len(sel) != 1:
            return
        tag = next(iter(sel))
        n = self.project.nodes.get(tag)
        if not n:
            return
        n.x, n.y, n.z = (UNITS.length_base(self.nd_x.value()),
                         UNITS.length_base(self.nd_y.value()),
                         UNITS.length_base(self.nd_z.value()))
        n.support = [cb.isChecked() for cb in self.nd_boxes]
        self._commit(f"Updated node {tag}")

    def _apply_element_props(self) -> None:
        sel = self.viewport.sel_elements
        if len(sel) != 1:
            return
        tag = next(iter(sel))
        e = self.project.elements.get(tag)
        if not e:
            return
        e.mat = self.el_mat.currentData()
        e.sec = self.el_sec.currentData()
        e.vecxz = [self.el_vx.value(), self.el_vy.value(), self.el_vz.value()]
        self._commit(f"Updated element {tag}")

    # ================================================================== tables
    def open_tables(self, tab: int = 0) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        dlg = TablesDialog(self.project, self)
        dlg.tabs.setCurrentIndex(tab)
        if not dlg.exec() or dlg.result_project is None:
            return
        self._adopt(dlg.result_project)
        self._clear_results()
        self._commit("Edited model tables")
        self.viewport.fit()

    # =================================================================== help
    def quick_start(self) -> None:
        QMessageBox.information(self, "Quick Start", (
            "<h3>OpenSees Studio — Quick Start</h3>"
            "<p>A graphical model generator for OpenSees.</p>"
            "<ol>"
            "<li><b>New Nodes (N)</b> — enter coordinates, optionally repeat with spacing.</li>"
            "<li><b>New Elements (E)</b> — select nodes first, then pick beam / truss / shell.</li>"
            "<li><b>Copy / Move (C)</b> and <b>Mirror (M)</b> — replicate storeys or spans.</li>"
            "<li><b>Supports (S)</b> — fixed, pinned or roller restraints.</li>"
            "<li><b>Load Cases</b>, <b>Nodal Loads (L)</b>, <b>Element Loads</b>, <b>Self Weight</b>.</li>"
            "<li><b>Combinations (K)</b> — factor each case.</li>"
            "<li><b>Run Static (F5)</b> or <b>Run Modal (F6)</b>, then inspect results (F7).</li>"
            "</ol>"
            "<p>The active load case is chosen in the status bar; loads are drawn for it.</p>"
            "<p><b>Mouse:</b> left = select / box-select, middle = pan, right = orbit, wheel = zoom.<br>"
            "<b>Tables (T)</b> edits every entity in a spreadsheet.</p>"))

    def about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}", (
            f"<h3>{APP_NAME}</h3>"
            "<p>Graphical model generation for OpenSees.</p>"
            "<p>Display units: " + UNITS.label() + ".<br>"
            "Model data is stored in kN, mm, tonne, s.<br>"
            "Engine: OpenSeesPy 3.8.0<br>"
            "Interface: PySide6 / Qt 6</p>"
            "<p>Features: nodes, beam/truss/shell elements, copy-move-mirror, "
            "supports, load cases, nodal and element loads, self weight, "
            "load combinations, static and modal analysis, deformed shapes, "
            "Tcl export and spreadsheet tables.</p>"))

    # ================================================================ shutdown
    def closeEvent(self, event) -> None:
        event.accept()
