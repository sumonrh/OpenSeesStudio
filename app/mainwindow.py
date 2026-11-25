"""Main application window (model generation UI)."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, List, Optional

from PySide6.QtCore import QMimeData, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QBrush, QColor, QCursor, QDesktopServices,
                           QFont, QKeySequence)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDockWidget, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QInputDialog, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QStackedWidget, QToolBar,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import (boundary_dialogs, dialogs, icons, opsgen, runcontrol,
               tablecopy, tcl, theme, wizards)
from .device_dialogs import DeviceDialog
from .dnd import MODEL_ITEM_MIME
from .faq import FaqDialog
from .wizard_dialog import StructureWizard
from .analysis_runner import AnalysisProgressDialog, AnalysisRunner
from .groundmotion_dialog import GroundMotionCatalogDialog
from .hinges import AssignHingesDialog, HingeLibraryDialog
from .hinge_catalog import (MATERIALS as HINGE_MATERIALS,
                            SPRING_HINGE_MATERIALS)
from .model import (BoundaryConstraint, DEVICE_KINDS, Element, LoadCase,
                    LiveLoadCase,
                    LoadCombination, Material, NodalLoad, Node, Project, Section,
                    SPRING_DOFS, SpringSupport, default_project, fmt)
from .pushover import PushoverResultsDialog
from .ribbon import Ribbon
from .results import ResultsDialog
from .resultsview import ResultsPanel
from .response_spectrum import ResponseSpectrumDialog, ResponseSpectrumResultsDialog
from .tables import TablesDialog
from .timehistory import TimeHistoryResultsDialog
from .toolbar_dialog import ToolbarCustomizeDialog
from .units import FORCE_UNITS, LENGTH_UNITS, UNITS
from .updates import UpdateChecker
from .version import APP_VERSION
from .viewport import Viewport

APP_NAME = "OpenSees Studio"
PROJECT_FILTER = "OpenSees Studio project (*.ospj);;JSON files (*.json);;All files (*)"
SUPPORT_PRESETS = {
    "fixed": [True] * 6,
    "pinned": [True, True, True, False, False, False],
    "roller_z": [True, True, False, False, False, False],
}
MAX_SELECTION_RANGE = 10000


def parse_selection_text(text: str) -> List[int]:
    """Parse tags such as ``1 2, 4 to 7`` into a sorted unique list."""
    tokens = str(text).replace(",", " ").split()
    tags: List[int] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        combined = re.fullmatch(r"(\d+)[tT][oO](\d+)", token)
        if combined:
            lo, hi = int(combined.group(1)), int(combined.group(2))
            i += 1
        elif i + 2 < len(tokens) and tokens[i + 1].lower() == "to":
            try:
                lo, hi = int(token), int(tokens[i + 2])
            except ValueError:
                i += 1
                continue
            i += 3
        else:
            try:
                tags.append(int(token))
            except ValueError:
                pass
            i += 1
            continue
        lo, hi = sorted((lo, hi))
        if hi - lo <= MAX_SELECTION_RANGE:
            tags.extend(range(lo, hi + 1))
    return sorted(set(tags))


def format_selection_tags(tags) -> str:
    """Format tags compactly, compressing runs of three or more."""
    numbers = sorted({int(tag) for tag in tags})
    if not numbers:
        return ""
    parts: List[str] = []
    run = [numbers[0]]
    for number in numbers[1:]:
        if number == run[-1] + 1:
            run.append(number)
            continue
        if len(run) >= 3:
            parts.append(f"{run[0]} to {run[-1]}")
        else:
            parts.extend(str(value) for value in run)
        run = [number]
    if len(run) >= 3:
        parts.append(f"{run[0]} to {run[-1]}")
    else:
        parts.extend(str(value) for value in run)
    return ", ".join(parts)


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


class ModelTree(QTreeWidget):
    """Model tree that exports draggable material/section/hinge/support items."""

    def mimeData(self, items):
        data = QMimeData()
        if not items:
            return data
        item_data = items[0].data(0, Qt.UserRole)
        if not item_data:
            return data
        kind, value = item_data
        if kind not in ("material", "section", "hinge", "support_preset"):
            return data
        data.setData(MODEL_ITEM_MIME,
                     json.dumps({"kind": kind, "value": value}).encode("utf-8"))
        data.setText(f"{kind}: {value}")
        return data


# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        tablecopy.install(QApplication.instance())
        self.project = default_project()
        UNITS.set(self.project.settings.get("force_unit", "kN"),
                  self.project.settings.get("length_unit", "mm"))
        self.history = History(self.project)
        self.static_results: Optional[opsgen.StaticResults] = None
        self.modal_results: Optional[opsgen.ModalResults] = None
        self.pushover_results: Optional[opsgen.PushoverResults] = None
        self.time_history_results: Optional[opsgen.TimeHistoryResults] = None
        self.response_spectrum_results: Optional[opsgen.ResponseSpectrumResults] = None
        self.analysis_runner: Optional[AnalysisRunner] = None
        self.console_dialog = None
        self.time_history_dialog = None
        self.time_history_step_scenario = ""
        self.response_spectrum_dialog = None
        self.static_cache: Dict[str, opsgen.StaticResults] = {}
        self.results_scenario = ""
        self.model_locked = False

        self.setWindowTitle(f"{APP_NAME} - Untitled")
        self.resize(1480, 940)
        self.setMinimumSize(1080, 700)

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)
        self.viewport.selectionChanged.connect(self._on_selection)
        self.viewport.statusMessage.connect(self._status)
        self.viewport.navigationCancelled.connect(self._sync_navigation_actions)
        self.viewport.modelItemDropped.connect(self._apply_tree_drop)
        self.viewport.contextMenuRequested.connect(self._viewport_context_menu)

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
        self._log("Start with Structure > New Nodes (N), then Batch Element (E) "
                  "or Draw Element.")
        self._log("Use the Structure tab wizards to generate frames, trusses "
                  "and girder bridges.")
        self._shown = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            QTimer.singleShot(0, self.viewport.fit)
            QTimer.singleShot(0, lambda: self.resizeDocks(
                [self.log_dock], [140], Qt.Vertical))
            QTimer.singleShot(0, self._show_research_disclaimer)

    def _show_research_disclaimer(self) -> None:
        """Show the research-use notice once per version outside automation."""
        if os.environ.get("OPENSEES_STUDIO_IN_PROCESS") == "1":
            return
        if any(arg in sys.argv for arg in
               ("--selftest", "--screenshot", "--bridge")):
            return
        settings = QSettings("OpenSees Studio", "OpenSees Studio")
        key = "research_disclaimer/version"
        if settings.value(key, "") == APP_VERSION:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Research use only")
        box.setText("OpenSees Studio is a research and education tool.")
        box.setInformativeText(
            "It is under active development and is currently an early alpha. "
            "Results are not fully verified and may contain errors. Test and "
            "verify all results independently before use. It is not intended "
            "for real-world commercial work, design decisions, or any "
            "application involving public safety.\n\n"
            "The software is provided as is, and you use it at your own risk. "
            "Do you understand and accept these conditions?")
        accept = box.addButton("I understand", QMessageBox.AcceptRole)
        box.addButton("Exit", QMessageBox.RejectRole)
        box.setDefaultButton(accept)
        box.exec()
        if box.clickedButton() is not accept:
            QTimer.singleShot(0, self.close)
            return
        settings.setValue(key, APP_VERSION)

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
        self.a_close = self._act("Close Project", "new", self.file_close, "Ctrl+W",
                                 "Close the current project and return to Untitled")
        self.a_save = self._act("Save", "save", self.file_save, "Ctrl+S", "Save the project")
        self.a_save_as = self._act("Save As", "save_as", self.file_save_as, "Ctrl+Shift+S")
        self.a_export_tcl = self._act("Export Tcl", "export", self.export_tcl, "",
                                      "Write an OpenSees Tcl input file")
        self.a_import_tcl = self._act(
            "Import Tcl", "import_tcl", self.import_tcl, "",
            "Import nodes, elements, supports and loads from an OpenSees Tcl file")
        self.a_console = self._act(
            "Script Console", "console", self.open_console, "",
            "Write and run OpenSeesPy Python or OpenSees Tcl model scripts")
        self.a_section_props = self._act(
            "Section Properties", "section_props", self.section_properties, "",
            "Calculate section properties and transfer them to the section library")
        self.a_moment_curvature = self._act(
            "Moment Curvature", "curvature", self.moment_curvature, "",
            "Create a moment-rotation backbone for pushover and nonlinear time history")
        self.a_live_load = self._act(
            "Live Load Case", "case", self.live_load, "",
            "Define a moving-load case from a saved vehicle and lane")
        self.a_lane_def = self._act(
            "Lanes", "lane", self.lane_definitions, "",
            "Define traffic lane start/end points, lateral shift and wheel lines")
        self.a_vehicle_def = self._act(
            "Vehicles", "truck", self.vehicle_definitions, "",
            "Define moving vehicles by axle loads and spacing")
        self.a_example = self._act("Example Frame", "example", self.load_example, "",
                                   "Load the built-in three-storey steel frame")
        self.a_exit = self._act("Exit", "exit", self.close, "Alt+F4")

        self.a_undo = self._act("Undo", "undo", self.undo, "Ctrl+Z")
        self.a_redo = self._act("Redo", "redo", self.redo, "Ctrl+Y")
        self.a_delete = self._act("Delete", "delete", self.delete_selection, "Del",
                                  "Delete the selected nodes and elements")
        self.a_sel_all = self._act("Select All", "select_all", self.viewport.select_all, "Ctrl+A")
        self.a_deselect = self._act("Deselect", "deselect", self._escape, "Esc")
        self.a_select = self._act(
            "Select", "select", self._toggle_select, "",
            "Select mode: click elements or nodes, or drag a selection box",
            checkable=True)
        self.a_pan = self._act(
            "Pan", "pan", self._toggle_pan, "P",
            "Pan mode: left-drag moves the view", checkable=True)

        self.a_fit = self._act("Fit", "fit", self.viewport.fit, "F", "Zoom to the whole model")
        self.a_iso = self._act("Iso", "iso", lambda: self.viewport.set_view("iso"), "Ctrl+1")
        self.a_top = self._act("Top", "top", lambda: self.viewport.set_view("top"), "Ctrl+2")
        self.a_front = self._act("Front", "front", lambda: self.viewport.set_view("front"), "Ctrl+3")
        self.a_right = self._act("Right", "right", lambda: self.viewport.set_view("right"), "Ctrl+4")
        self.a_fit_sel = self._act("Fit selection", "fit_selection", self.viewport.fit_selection, "")

        self.a_nodes = self._act("New Nodes", "node", self.new_nodes, "N",
                                 "Create nodes by coordinates")
        self.a_elements = self._act("Batch Element", "batch_element", self.new_elements, "E",
                                    "Create multiple elements between selected nodes")
        self.a_draw_element = self._act(
            "Draw Element", "draw_element", self.toggle_draw_element, "",
            "Draw beam elements by clicking from one node to another",
            checkable=True)
        self.a_draw_element.triggered.disconnect()
        self.a_draw_element.toggled.connect(self.toggle_draw_element)
        self.a_wiz_frame2d = self._act(
            "2D Frame", "frame2d", lambda *_: self.run_wizard("frame2d"), "",
            "Generate a 2D moment frame from bays, storeys and sections")
        self.a_wiz_frame3d = self._act(
            "3D Frame", "frame3d", lambda *_: self.run_wizard("frame3d"), "",
            "Generate a 3D moment frame from bays, storeys and sections")
        self.a_wiz_truss2d = self._act(
            "2D Truss", "truss2d", lambda *_: self.run_wizard("truss2d"), "",
            "Generate a simply supported planar truss")
        self.a_wiz_truss3d = self._act(
            "3D Truss", "truss3d", lambda *_: self.run_wizard("truss3d"), "",
            "Generate a rectangular space truss")
        self.a_wiz_bridge = self._act(
            "Girder Bridge", "bridge", lambda *_: self.run_wizard("bridge"), "",
            "Generate a multi-span concrete or steel girder bridge grillage")
        self.a_copy = self._act("Copy / Move", "copy", self.copy_move, "C")
        self.a_subdivide = self._act("Subdivide", "subdivide", self.subdivide, "",
                                     "Split selected beam or truss elements into "
                                     "equal parts")
        self.a_mirror = self._act("Mirror", "mirror", self.mirror, "M",
                                  "Mirror selected nodes and elements about a "
                                  "coordinate plane")
        self.a_support = self._act("Supports", "support", self.assign_supports, "S")
        self.a_spring = self._act(
            "Point Spring", "spring", self.add_point_springs, "",
            "Create zeroLength spring supports (linear, multi-linear or p-y)")
        self.a_rigid_link = self._act(
            "Rigid Link", "rigid_link", self.add_rigid_link, "",
            "Connect master and slave nodes with a rigid beam or bar")
        self.a_equal_dof = self._act(
            "Equal DOF", "equal_dof", self.add_equal_dof, "",
            "Tie selected DOFs of slave nodes to a master node")
        self.a_diaphragm = self._act(
            "Diaphragm", "diaphragm", self.add_diaphragm, "",
            "Create a rigid diaphragm constraint about a global axis")
        self.a_bearing = self._act(
            "Bearing", "bearing", lambda *_: self.add_device("bearing"), "",
            "Create an elastomeric bearing with a Bouc-Wen shear law")
        self.a_isolator = self._act(
            "Isolator", "isolator", lambda *_: self.add_device("isolator"), "",
            "Create a lead-rubber isolator (OpenSees LeadRubberX)")
        self.a_damper = self._act(
            "Damper", "damper", lambda *_: self.add_device("damper"), "",
            "Create a viscous or bilinear oil damper between two nodes")
        self.a_material = self._act("Materials", "material", self.materials, "")
        self.a_section = self._act("Sections", "section", self.sections, "")
        self.a_tables = self._act("Tables", "tables", self.open_tables_for_current_tab, "T")
        self.a_tables_nodes = self._act(
            "Node Table", "tables", lambda: self.open_tables(0), "",
            "Open the node table")
        self.a_tables_supports = self._act(
            "Support Table", "tables", lambda: self.open_tables(1), "",
            "Open the supports table")
        self.a_tables_elements = self._act(
            "Element Table", "tables", lambda: self.open_tables(2), "",
            "Open the element table")
        self.a_tables_materials = self._act(
            "Material Table", "tables", lambda: self.open_tables(3), "",
            "Open the material table")
        self.a_tables_sections = self._act(
            "Section Table", "tables", lambda: self.open_tables(4), "",
            "Open the section table")
        self.a_tables_cases = self._act(
            "Load Case Table", "tables", lambda: self.open_tables(5), "",
            "Open the load-case table")
        self.a_tables_nodal = self._act(
            "Nodal Load Table", "tables", lambda: self.open_tables(6), "",
            "Open the nodal-load table")
        self.a_tables_element_loads = self._act(
            "Element Load Table", "tables", lambda: self.open_tables(7), "",
            "Open the element-load table")
        self.a_tables_combos = self._act(
            "Combination Table", "tables", lambda: self.open_tables(8), "",
            "Open the load-combination table")

        self.a_cases = self._act("Load Cases", "case", self.load_cases, "")
        self.a_nload = self._act("Nodal Loads", "nodal_load", self.nodal_loads, "L")
        self.a_eload = self._act("Element Loads", "element_load", self.element_loads, "")
        self.a_sw = self._act("Self Weight", "self_weight", self.self_weight, "")
        self.a_combo = self._act("Combinations", "combo", self.combinations, "K")

        self.a_settings = self._act("Settings", "settings", self.analysis_settings, "")
        self.a_modal_settings = self._act(
            "Modal Settings", "modal", self.modal_settings, "",
            "Set the number of modes, eigen solver and mass option")
        self.a_check = self._act("Check Model", "check", self.check_model, "F9",
                                 "Validate the model before analysis")
        self.a_run = self._act("Run Analysis", "run", self.run_analysis_control, "F5",
                               "Choose the analyses to run (static, modal, pushover, "
                               "time history, response spectrum)")
        self.a_modal = self._act("Modal", "modal", self.run_modal, "F6",
                                 "Run an eigenvalue analysis")
        self.a_results = self._act("Results", "results", self.show_results, "F7")
        self.a_beam_diagram = self._act(
            "Beam Diagrams", "diagram", self._toggle_beam_diagram, "",
            "Show shear, moment, axial and torsion diagrams for a load case "
            "or combination", checkable=True)
        self.a_deformation = self._act(
            "Deformation", "deformed", self._toggle_deformation, "",
            "Show the deformed shape of a load case or combination",
            checkable=True)
        self.a_reactions = self._act(
            "Reactions", "reactions", self._toggle_reactions, "",
            "Show support reaction arrows scaled by magnitude",
            checkable=True)

        self.a_orbit = self._act("Orbit", "rotate", self._toggle_orbit, "O",
                                 "3D orbit: left-drag rotates the model "
                                 "(Shift+left or Shift+middle always orbits)", checkable=True)
        self.a_select.setChecked(True)
        self.a_node_labels = self._act(
            "Node Labels", "node_label", lambda on: self._toggle(node_labels=on), "",
            "Show node tags in the viewport", checkable=True)
        self.a_element_labels = self._act(
            "Element Labels", "element_label", lambda on: self._toggle(element_labels=on), "",
            "Show element tags in the viewport", checkable=True)
        self.a_grid = self._act("Grid", "grid", lambda on: self._toggle(grid=on),
                                "", checkable=True)
        self.a_grid.setChecked(True)
        self.a_deformed = self._act("Deformed", "deformed",
                                    lambda on: self._toggle(deformed=on), "", checkable=True)
        self.a_deformed.setChecked(True)
        self.a_nodes_visible = self._act("Nodes", "node",
                                         lambda on: self._toggle(nodes=on), "",
                                         "Show or hide nodes in the viewport",
                                         checkable=True)
        self.a_nodes_visible.setChecked(True)
        self.a_activate = self._act(
            "Activate", "activate", self.activate_selection, "",
            "Show only the selected nodes/elements; hide the rest")
        self.a_deactivate = self._act(
            "Deactivate", "deactivate", self.deactivate_selection, "",
            "Hide the selected nodes/elements from the view")
        self.a_activate_all = self._act(
            "Activate All", "activate_all", self.activate_all, "",
            "Show all nodes and elements again")
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumWidth(170)
        self.mode_combo.setMaximumWidth(260)
        self.mode_combo.setToolTip("Select a mode shape to display")
        self.mode_combo.currentIndexChanged.connect(self._mode_selected)
        self.a_animate = self._act("Animate", "animate", self.animate_mode, "F8", checkable=True)
        self.a_pushover = self._act(
            "Pushover", "pushover", self.pushover, "",
            "Run a displacement-controlled pushover with lumped plastic hinges")
        self.a_hinge_defs = self._act(
            "Define Hinges", "hinge", self.edit_hinge_defs, "",
            "Create and edit reusable lumped plastic-hinge definitions")
        self.a_hinge_assign = self._act(
            "Assign Hinges", "hinge_assign", self.assign_hinges, "",
            "Assign hinge definitions to selected beam elements")
        self.a_pushover_results = self._act(
            "Pushover Results", "results", self.show_pushover_results, "",
            "Show the capacity curve and hinge state")
        self.a_pushover_results.setEnabled(False)
        self.a_ground_motion = self._act(
            "TH Case", "settings", self.define_time_history, "",
            "Define the time-history case and ground-motion source")
        self.a_gm_catalog = self._act(
            "GM Catalog", "load_show", self.ground_motion_catalog, "",
            "Manage the project ground-motion catalog")
        self.a_time_history = self._act(
            "Time History", "run_static", self.run_time_history, "",
            "Run a uniform-excitation time-history analysis")
        self.a_time_history_results = self._act(
            "TH Results", "results", self.show_time_history_results, "",
            "Show the time-history response")
        self.a_time_history_results.setEnabled(False)
        self.a_spectrum_case = self._act(
            "RS Case", "settings", self.define_response_spectrum, "",
            "Define the response spectrum and modal combination")
        self.a_spectrum = self._act(
            "Response Spectrum", "run_static", self.run_response_spectrum, "",
            "Run a response-spectrum analysis")
        self.a_spectrum_results = self._act(
            "RS Results", "results", self.show_response_spectrum_results, "",
            "Show the response-spectrum results")
        self.a_spectrum_results.setEnabled(False)
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
        self.a_constraints_visible = self._act(
            "Links", "rigid_link",
            lambda on: self._toggle(constraints=on), "",
            "Show or hide rigid links, equalDOF and diaphragm constraints",
            checkable=True)
        self.a_constraints_visible.setChecked(True)
        self.a_lock = self._act("Lock", "unlock", self._toggle_lock, "Ctrl+L",
                                "Lock model editing to protect analysis results",
                                checkable=True)
        self.a_model_visible = self._act("Model", "panel_model",
                                         lambda on: self.model_dock.setVisible(on), "",
                                         "Show or hide the model tree", checkable=True)
        self.a_model_visible.setChecked(True)
        self.a_groups_visible = self._act(
            "Groups", "panel_model",
            lambda on: self.groups_dock.setVisible(on), "",
            "Show or hide structure and boundary groups", checkable=True)
        self.a_groups_visible.setChecked(True)
        self.a_props_visible = self._act("Properties", "panel_props",
                                         lambda on: self.props_dock.setVisible(on), "",
                                         "Show or hide the properties panel", checkable=True)
        self.a_props_visible.setChecked(False)
        self.a_log_visible = self._act("Messages", "panel_log",
                                       lambda on: self.log_dock.setVisible(on), "",
                                       "Show or hide the messages panel", checkable=True)
        self.a_log_visible.setChecked(True)
        self.a_toolbars = self._act(
            "Toolbars", "settings", self._toolbar_choice_menu, "",
            "Choose and arrange the buttons on the quick toolbars")
        self.a_quick = self._act("Quick Start", "help", self.quick_start, "F1")
        self.a_faq = self._act("FAQ", "help", self.show_faq, "",
                               "Frequently asked questions and OpenSees help")
        self.a_opensees_help = self._act(
            "OpenSees Help", "open", self.open_opensees_help, "",
            "Open the official OpenSees wiki and documentation")
        self.a_about = self._act("About", "about", self.about, "")

        self.edit_actions = (self.a_nodes, self.a_elements, self.a_draw_element,
                             self.a_wiz_frame2d, self.a_wiz_frame3d,
                             self.a_wiz_truss2d, self.a_wiz_truss3d, self.a_wiz_bridge,
                             self.a_copy, self.a_subdivide,
                             self.a_mirror, self.a_support, self.a_material,
                             self.a_spring, self.a_rigid_link, self.a_equal_dof,
                             self.a_diaphragm, self.a_bearing, self.a_isolator,
                             self.a_damper,
                             self.a_section, self.a_hinge_defs, self.a_hinge_assign,
                             self.a_tables, self.a_tables_nodes,
                             self.a_tables_supports, self.a_tables_elements,
                             self.a_tables_materials, self.a_tables_sections,
                             self.a_tables_cases, self.a_tables_nodal,
                             self.a_tables_element_loads, self.a_tables_combos,
                             self.a_cases, self.a_nload, self.a_eload, self.a_sw,
                             self.a_combo, self.a_delete, self.a_undo, self.a_redo,
                             self.a_settings, self.a_modal_settings, self.a_ground_motion,
                             self.a_gm_catalog, self.a_spectrum_case,
                             self.a_import_tcl, self.a_section_props,
                             self.a_moment_curvature, self.a_live_load,
                             self.a_lane_def, self.a_vehicle_def)

    def _toggle(self, node_labels=None, element_labels=None, grid=None, deformed=None,
                loads=None, supports=None, extruded=None, nodes=None,
                constraints=None) -> None:
        kw = {}
        if node_labels is not None:
            kw["show_node_labels"] = node_labels
        if element_labels is not None:
            kw["show_element_labels"] = element_labels
        if grid is not None:
            kw["show_grid"] = grid
        if deformed is not None:
            kw["show_deformed"] = deformed
        if loads is not None:
            kw["show_loads"] = loads
        if supports is not None:
            kw["show_supports"] = supports
        if constraints is not None:
            kw["show_constraints"] = constraints
        if extruded is not None:
            kw["show_extruded"] = extruded
        if nodes is not None:
            kw["show_nodes"] = nodes
        self.viewport.set_show(**kw)

    def activate_selection(self) -> None:
        if not (self.viewport.sel_nodes or self.viewport.sel_elements):
            self._warn("Select nodes or elements first.")
            return
        if self.viewport.show_only_selected():
            self._status("Activate: only selected nodes/elements are shown")
        else:
            self._warn("Select nodes or elements first.")

    def deactivate_selection(self) -> None:
        if not (self.viewport.sel_nodes or self.viewport.sel_elements):
            self._warn("Select nodes or elements first.")
            return
        if self.viewport.hide_selected():
            self._status("Deactivate: selected nodes/elements hidden")
        else:
            self._warn("Select nodes or elements first.")

    def activate_all(self) -> None:
        self.viewport.clear_visibility()
        self._status("Activate All: all nodes and elements are visible")

    def clean_view(self) -> None:
        self.viewport.stop_animation()
        self.viewport.clear_diagrams()
        self.viewport.clear_reactions()
        self.viewport.set_show(show_deformed=False, show_loads=False,
                               show_node_labels=False, show_element_labels=False)
        for action, state in ((self.a_deformed, False),
                              (self.a_loads_visible, False),
                              (self.a_node_labels, False),
                              (self.a_element_labels, False),
                              (self.a_animate, False),
                              (self.a_beam_diagram, False),
                              (self.a_deformation, False),
                              (self.a_reactions, False)):
            action.blockSignals(True)
            action.setChecked(state)
            action.blockSignals(False)
        self._status("Clean view: deformation, loads and labels hidden")

    def _toggle_select(self, checked: bool) -> None:
        if not checked:
            if not (self.viewport.orbit_mode or self.viewport.pan_mode):
                self.a_select.setChecked(True)
            return
        self.a_pan.setChecked(False)
        self.a_orbit.setChecked(False)
        self.viewport.orbit_mode = False
        self.viewport.pan_mode = False
        self.viewport.setCursor(Qt.ArrowCursor)
        self.viewport.statusMessage.emit(
            "Select mode: click or drag to select")

    def _toggle_pan(self, checked: bool) -> None:
        if checked:
            self.a_orbit.setChecked(False)
            self.a_select.setChecked(False)
            self.viewport.orbit_mode = False
            self.viewport.set_pan_mode(True)
        else:
            self.viewport.set_pan_mode(False)
            if not self.viewport.orbit_mode:
                self.a_select.setChecked(True)

    def _toggle_orbit(self, checked: bool) -> None:
        if checked:
            self.a_pan.setChecked(False)
            self.a_select.setChecked(False)
            self.viewport.pan_mode = False
            self.viewport.set_orbit_mode(True)
        else:
            self.viewport.set_orbit_mode(False)
            if not self.viewport.pan_mode:
                self.a_select.setChecked(True)

    def _sync_navigation_actions(self) -> None:
        self.a_orbit.setChecked(self.viewport.orbit_mode)
        self.a_pan.setChecked(self.viewport.pan_mode)
        self.a_select.setChecked(
            not (self.viewport.orbit_mode or self.viewport.pan_mode))

    def _escape(self) -> None:
        if self.viewport.draw_element_mode:
            self._cancel_draw_mode()
            self._status("Draw element finished")
            return
        if self.viewport.orbit_mode:
            self.a_orbit.setChecked(False)
            self.viewport.set_orbit_mode(False)
            self.a_select.setChecked(True)
            return
        if self.viewport.pan_mode:
            self.a_pan.setChecked(False)
            self.viewport.set_pan_mode(False)
            self.a_select.setChecked(True)
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
        if locked and self.a_draw_element.isChecked():
            self.a_draw_element.setChecked(False)
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
        if hasattr(self, "results_panel"):
            self.results_panel.set_deformation_scale(float(value))
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
        menu.addAction(self.a_close)
        menu.addSeparator()
        menu.addAction(self.a_save)
        menu.addAction(self.a_save_as)
        menu.addSeparator()
        menu.addAction(self.a_export_tcl)
        menu.addAction(self.a_import_tcl)
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
        for action in (self.a_fit, self.a_iso, self.a_top, self.a_front,
                       self.a_right, self.a_pan, self.a_orbit, self.a_fit_sel):
            group.add_large(action)
        group = page.add_group("Display")
        group.add_column((self.a_nodes_visible, self.a_node_labels,
                          self.a_element_labels))
        group.add_column((self.a_grid, self.a_supports_visible,
                          self.a_constraints_visible))
        group = page.add_group("Visibility")
        group.add_large(self.a_activate)
        group.add_large(self.a_deactivate)
        group.add_large(self.a_activate_all)
        group = page.add_group("Deformed shape")
        group.add_field("Scale", self.scale_spin)
        group = page.add_group("View mode")
        group.add_large(self.a_extruded)
        group = page.add_group("Panels")
        group.add_column((self.a_model_visible, self.a_groups_visible,
                          self.a_props_visible))
        group.add_column((self.a_log_visible, self.a_toolbars))

        page = ribbon.add_tab("Structure")
        group = page.add_group("Frame wizards")
        group.add_large(self.a_wiz_frame2d)
        group.add_large(self.a_wiz_frame3d)
        group = page.add_group("Truss wizards")
        group.add_large(self.a_wiz_truss2d)
        group.add_large(self.a_wiz_truss3d)
        group = page.add_group("Bridge wizard")
        group.add_large(self.a_wiz_bridge)
        group = page.add_group("Devices")
        group.add_large(self.a_bearing)
        group.add_large(self.a_isolator)
        group.add_large(self.a_damper)
        group = page.add_group("Example")
        group.add_large(self.a_example)

        page = ribbon.add_tab("Node/Element")
        group = page.add_group("Nodes")
        group.add_large(self.a_nodes)
        group = page.add_group("Selection")
        group.add_column((self.a_sel_all, self.a_deselect))
        group = page.add_group("Elements")
        group.add_large(self.a_elements)
        group.add_large(self.a_draw_element)
        group.add_large(self.a_subdivide)
        group = page.add_group("Modify")
        group.add_large(self.a_copy)
        group.add_large(self.a_mirror)
        group.add_large(self.a_delete)
        group = page.add_group("Model data")
        group.add_large(self.a_tables_nodes)
        group.add_large(self.a_tables_elements)

        page = ribbon.add_tab("Properties")
        group = page.add_group("Libraries")
        group.add_large(self.a_material)
        group.add_large(self.a_section)
        group = page.add_group("Model data")
        group.add_large(self.a_tables_materials)
        group.add_large(self.a_tables_sections)

        page = ribbon.add_tab("Boundary")
        group = page.add_group("Supports and springs")
        group.add_large(self.a_support)
        group.add_large(self.a_spring)
        group = page.add_group("Constraints")
        group.add_large(self.a_rigid_link)
        group.add_large(self.a_equal_dof)
        group.add_large(self.a_diaphragm)
        group = page.add_group("Model data")
        group.add_large(self.a_tables_supports)

        page = ribbon.add_tab("Load")
        group = page.add_group("Load cases")
        group.add_large(self.a_cases)
        group.add_large(self.a_combo)
        group = page.add_group("Structural loads")
        group.add_large(self.a_nload)
        group.add_large(self.a_eload)
        group.add_large(self.a_sw)
        group = page.add_group("Display")
        group.add_column((self.a_loads_visible,))
        group = page.add_group("Live load")
        group.add_large(self.a_vehicle_def)
        group.add_large(self.a_lane_def)
        group.add_large(self.a_live_load)
        group = page.add_group("Model data")
        group.add_large(self.a_tables_cases)
        group.add_column((self.a_tables_nodal, self.a_tables_element_loads,
                          self.a_tables_combos))

        page = ribbon.add_tab("Analysis")
        group = page.add_group("Analysis")
        group.add_large(self.a_settings)
        group.add_large(self.a_modal_settings)
        group.add_large(self.a_check)
        group.add_large(self.a_run)
        group = page.add_group("Results")
        group.add_large(self.a_results)
        group = page.add_group("Model state")
        group.add_large(self.a_lock)

        page = ribbon.add_tab("Dynamic")
        group = page.add_group("Ground motions")
        group.add_large(self.a_gm_catalog)
        group.add_large(self.a_ground_motion)
        group = page.add_group("Time history")
        group.add_large(self.a_time_history)
        group.add_large(self.a_time_history_results)
        group = page.add_group("Response spectrum")
        group.add_large(self.a_spectrum_case)
        group.add_large(self.a_spectrum)
        group.add_large(self.a_spectrum_results)
        group = page.add_group("Modal analysis")
        group.add_large(self.a_modal)
        group = page.add_group("Model state")
        group.add_large(self.a_lock)

        page = ribbon.add_tab("Pushover")
        group = page.add_group("Pushover")
        group.add_large(self.a_pushover)
        group = page.add_group("Hinges")
        group.add_large(self.a_hinge_defs)
        group.add_large(self.a_hinge_assign)
        group = page.add_group("Model state")
        group.add_large(self.a_lock)

        page = ribbon.add_tab("Results")
        group = page.add_group("Results")
        group.add_large(self.a_results)
        group.add_large(self.a_pushover_results)
        group.add_large(self.a_time_history_results)
        group.add_large(self.a_spectrum_results)
        group = page.add_group("Mode shapes")
        group.add_field("Mode", self.mode_combo)
        group.add_large(self.a_animate)
        group = page.add_group("Result display")
        group.add_large(self.a_beam_diagram)
        group.add_large(self.a_deformation)
        group.add_large(self.a_reactions)
        group = page.add_group("Model state")
        group.add_large(self.a_lock)

        page = ribbon.add_tab("Tools")
        group = page.add_group("Project")
        group.add_large(self.a_new)
        group.add_large(self.a_open)
        group.add_large(self.a_save)
        group = page.add_group("Exchange")
        group.add_large(self.a_export_tcl)
        group.add_large(self.a_import_tcl)
        group = page.add_group("Design tools")
        group.add_large(self.a_section_props)
        group.add_large(self.a_moment_curvature)
        group = page.add_group("Scripting")
        group.add_large(self.a_console)

        page = ribbon.add_tab("Help")
        group = page.add_group("OpenSees Studio")
        group.add_large(self.a_quick)
        group.add_large(self.a_faq)
        group.add_large(self.a_about)
        group = page.add_group("OpenSees")
        group.add_large(self.a_opensees_help)

        self.update_button = QToolButton()
        self.update_button.setObjectName("updateBadge")
        self.update_button.setIcon(icons.icon("update", 16))
        self.update_button.setIconSize(QSize(16, 16))
        self.update_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.update_button.setText("Update")
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.setToolTip("A newer OpenSees Studio installer is available")
        self.update_button.clicked.connect(self._open_update)
        self.update_button.hide()
        ribbon.add_corner_widget(self.update_button)
        self.update_url = ""
        self.update_version = ""
        self.update_checker = UpdateChecker(APP_VERSION, self)
        self.update_checker.available.connect(self._show_update)
        QTimer.singleShot(1200, self.update_checker.check)

        ribbon.set_current("Structure")

    def _make_quick_toolbars(self) -> None:
        """Create the customizable horizontal and vertical quick toolbars."""
        self._toolbar_registry: Dict[str, QAction] = {}
        catalog = []
        for name in sorted(n for n in dir(self) if n.startswith("a_")):
            action = getattr(self, name)
            if isinstance(action, QAction) and action.text():
                self._toolbar_registry[name] = action
                catalog.append((name, action.text()))
        catalog.sort(key=lambda pair: pair[1].lower())
        catalog.append(("separator", "Separator"))
        self._toolbar_catalog = catalog

        self._toolbar_defaults = {
            "quick": ["a_save", "separator", "a_run", "a_results",
                      "a_reactions", "a_check", "separator", "a_lock",
                      "a_nodes_visible", "separator", "a_activate",
                      "a_deactivate", "a_activate_all", "separator",
                      "a_undo", "a_redo"],
            "views": ["a_fit", "a_iso", "a_top", "a_front", "a_right",
                      "separator", "a_pan", "a_orbit", "a_node_labels",
                      "a_element_labels", "a_grid", "a_deformed",
                      "a_extruded", "a_clean_view", "separator", "a_fit_sel"],
        }
        self._toolbar_settings = QSettings("OpenSees Studio", "OpenSees Studio")
        self._toolbar_state = {
            name: self._load_toolbar_keys(name, defaults)
            for name, defaults in self._toolbar_defaults.items()
        }
        added = str(self._toolbar_settings.value(
            "toolbar/pan_added", "")).lower()
        if added not in ("1", "true"):
            views = self._toolbar_state["views"]
            if "a_pan" not in views:
                index = (views.index("a_orbit")
                         if "a_orbit" in views else len(views))
                views.insert(index, "a_pan")
            self._toolbar_settings.setValue("toolbar/pan_added", True)
        reactions_added = str(self._toolbar_settings.value(
            "toolbar/reactions_v1_added", "")).lower()
        if reactions_added not in ("1", "true"):
            quick_keys = self._toolbar_state["quick"]
            if "a_reactions" not in quick_keys:
                index = (quick_keys.index("a_results") + 1
                         if "a_results" in quick_keys else len(quick_keys))
                quick_keys.insert(index, "a_reactions")
                self._save_toolbar_keys("quick")
            self._toolbar_settings.setValue("toolbar/reactions_v1_added", True)

        quick = QToolBar("Quick access", self)
        quick.setObjectName("quick_toolbar")
        quick.setMovable(True)
        quick.setFloatable(True)
        quick.setContextMenuPolicy(Qt.CustomContextMenu)
        quick.customContextMenuRequested.connect(
            lambda pos: self._toolbar_context_menu(
                "quick", quick.mapToGlobal(pos)))
        quick.setToolButtonStyle(Qt.ToolButtonIconOnly)
        quick.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.TopToolBarArea, quick)
        self.quick_toolbar = quick
        self._populate_toolbar(quick, self._toolbar_state["quick"])

        self._element_history: List[str] = []
        self._node_history: List[str] = []
        selection = QToolBar("Selection", self)
        selection.setObjectName("selection_toolbar")
        selection.setMovable(True)
        selection.setFloatable(False)
        selection.setToolButtonStyle(Qt.ToolButtonIconOnly)
        selection.setIconSize(QSize(18, 18))
        selection.addAction(self.a_select)
        selection.addSeparator()
        selection.addWidget(QLabel("Elements"))
        self.element_combo = self._selection_combo("element")
        selection.addWidget(self.element_combo)
        selection.addSeparator()
        selection.addWidget(QLabel("Nodes"))
        self.node_combo = self._selection_combo("node")
        selection.addWidget(self.node_combo)
        self.addToolBar(Qt.TopToolBarArea, selection)
        self.selection_toolbar = selection

        views = QToolBar("Quick views", self)
        views.setObjectName("quickview_toolbar")
        views.setMovable(True)
        views.setFloatable(True)
        views.setContextMenuPolicy(Qt.CustomContextMenu)
        views.customContextMenuRequested.connect(
            lambda pos: self._toolbar_context_menu(
                "views", views.mapToGlobal(pos)))
        views.setToolButtonStyle(Qt.ToolButtonIconOnly)
        views.setIconSize(QSize(18, 18))
        views.setFixedWidth(38)
        self.addToolBar(Qt.RightToolBarArea, views)
        self.quick_view_toolbar = views
        self._populate_toolbar(views, self._toolbar_state["views"])

    def _load_toolbar_keys(self, name: str, defaults: List[str]) -> List[str]:
        import os
        if os.environ.get("OPENSEES_STUDIO_IN_PROCESS") == "1":
            return list(defaults)
        stored = self._toolbar_settings.value(f"toolbar/{name}", [])
        if isinstance(stored, str):
            stored = [stored]
        keys = [str(key) for key in (stored or [])
                if key == "separator" or str(key) in self._toolbar_registry]
        return keys or list(defaults)

    def _populate_toolbar(self, toolbar: QToolBar, keys: List[str]) -> None:
        toolbar.clear()
        for key in keys:
            if key == "separator":
                toolbar.addSeparator()
            elif key in self._toolbar_registry:
                toolbar.addAction(self._toolbar_registry[key])

    def _selection_combo(self, kind: str) -> QComboBox:
        combo = QComboBox(self)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMaxCount(5)
        combo.setMaxVisibleItems(6)
        combo.setMinimumContentsLength(18)
        combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumWidth(210)
        combo.setToolTip(
            f"Type {kind} numbers separated by spaces or commas, or a range "
            f"such as 4 to 9, then press Enter. The last five selection "
            f"lists are kept in the dropdown.")
        combo.lineEdit().setPlaceholderText("1 2, 4 to 9")
        combo.lineEdit().returnPressed.connect(
            lambda: self._apply_selection_text(kind))
        combo.activated.connect(
            lambda _index: self._apply_selection_text(kind))
        return combo

    def _apply_selection_text(self, kind: str) -> None:
        combo = self.element_combo if kind == "element" else self.node_combo
        text = combo.currentText().strip()
        if not text:
            self.viewport.clear_selection()
            self._status("Selection cleared")
            return
        tags = parse_selection_text(text)
        source = (self.project.elements if kind == "element"
                  else self.project.nodes)
        valid = [tag for tag in tags if tag in source]
        if not valid:
            self._status(f"No matching {kind}s in \"{text}\"")
            return
        if kind == "element":
            self.viewport.select_elements(valid)
        else:
            self.viewport.select_nodes(valid)
        missing = len(tags) - len(valid)
        note = f" ({missing} not found)" if missing else ""
        self._status(f"Selected {len(valid)} {kind}(s){note}")

    def _sync_selection_boxes(self) -> None:
        if not hasattr(self, "element_combo"):
            return
        self._set_selection_text(
            self.element_combo, self._element_history,
            format_selection_tags(self.viewport.sel_elements))
        self._set_selection_text(
            self.node_combo, self._node_history,
            format_selection_tags(self.viewport.sel_nodes))

    def _set_selection_text(self, combo: QComboBox,
                            history: List[str], text: str) -> None:
        if text:
            if text in history:
                history.remove(text)
            history.insert(0, text)
            del history[5:]
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(history)
        combo.setEditText(text)
        combo.blockSignals(False)

    def _toolbar_context_menu(self, which: str, pos) -> None:
        menu = QMenu(self)
        customize = menu.addAction("Customize Toolbar...")
        customize.triggered.connect(lambda: self._customize_toolbar(which))
        reset = menu.addAction("Reset Toolbar")
        reset.triggered.connect(lambda: self._reset_toolbar(which))
        menu.addSeparator()
        toolbar = (self.quick_toolbar if which == "quick"
                   else self.quick_view_toolbar)
        hide = menu.addAction("Hide Toolbar")
        hide.triggered.connect(toolbar.hide)
        menu.exec(pos)

    def _toolbar_choice_menu(self) -> None:
        menu = QMenu(self)
        quick = menu.addAction("Quick Access")
        quick.setCheckable(True)
        quick.setChecked(not self.quick_toolbar.isHidden())
        quick.triggered.connect(
            lambda checked: self.quick_toolbar.setVisible(bool(checked)))
        views = menu.addAction("Quick Views")
        views.setCheckable(True)
        views.setChecked(not self.quick_view_toolbar.isHidden())
        views.triggered.connect(
            lambda checked: self.quick_view_toolbar.setVisible(bool(checked)))
        selection = menu.addAction("Selection")
        selection.setCheckable(True)
        selection.setChecked(not self.selection_toolbar.isHidden())
        selection.triggered.connect(
            lambda checked: self.selection_toolbar.setVisible(bool(checked)))
        menu.addSeparator()
        menu.addAction("Customize Quick Access...",
                       lambda: self._customize_toolbar("quick"))
        menu.addAction("Customize Quick Views...",
                       lambda: self._customize_toolbar("views"))
        menu.addSeparator()
        menu.addAction("Reset Quick Access",
                       lambda: self._reset_toolbar("quick"))
        menu.addAction("Reset Quick Views",
                       lambda: self._reset_toolbar("views"))
        menu.exec(QCursor.pos())

    def _customize_toolbar(self, which: str) -> None:
        if which not in self._toolbar_defaults:
            return
        title = ("Customize Quick Access" if which == "quick"
                 else "Customize Quick Views")
        dialog = ToolbarCustomizeDialog(
            title, self._toolbar_catalog, self._toolbar_state[which],
            self._toolbar_defaults[which], self)
        if not dialog.exec():
            return
        keys = dialog.selected_keys()
        self._toolbar_state[which] = keys
        self._populate_toolbar(
            self.quick_toolbar if which == "quick" else self.quick_view_toolbar,
            keys)
        self._save_toolbar_keys(which)

    def _reset_toolbar(self, which: str) -> None:
        if which not in self._toolbar_defaults:
            return
        self._toolbar_state[which] = list(self._toolbar_defaults[which])
        self._populate_toolbar(
            self.quick_toolbar if which == "quick" else self.quick_view_toolbar,
            self._toolbar_state[which])
        self._save_toolbar_keys(which)

    def _save_toolbar_keys(self, which: str) -> None:
        import os
        if os.environ.get("OPENSEES_STUDIO_IN_PROCESS") == "1":
            return
        self._toolbar_settings.setValue(
            f"toolbar/{which}", self._toolbar_state[which])
        self._toolbar_settings.sync()

    # ============================================================ results view
    def _toggle_beam_diagram(self, checked: bool) -> None:
        if checked:
            self.results_dock.show()
            self.results_dock.raise_()
            self.results_panel.show_diagram_tab()
            self._refresh_results_panel()
            self._apply_beam_diagram()
        else:
            self.viewport.clear_diagrams()
            if not self.a_deformation.isChecked() and not self.a_reactions.isChecked():
                self.viewport.show_deformed = False
                self.a_deformed.blockSignals(True)
                self.a_deformed.setChecked(False)
                self.a_deformed.blockSignals(False)
                self.results_dock.hide()

    def _toggle_deformation(self, checked: bool) -> None:
        if checked:
            self.results_dock.show()
            self.results_dock.raise_()
            self.results_panel.show_deformation_tab()
            self._refresh_results_panel()
            self._apply_deformation()
        else:
            self.viewport.show_deformed = False
            self.a_deformed.blockSignals(True)
            self.a_deformed.setChecked(False)
            self.a_deformed.blockSignals(False)
            if not self.a_beam_diagram.isChecked() and not self.a_reactions.isChecked():
                self.results_dock.hide()

    def _toggle_reactions(self, checked: bool) -> None:
        if checked:
            self.results_dock.show()
            self.results_dock.raise_()
            self.results_panel.show_reactions_tab()
            self._refresh_results_panel()
            self._apply_reactions()
        else:
            self.viewport.clear_reactions()
            if not self.a_beam_diagram.isChecked() and not self.a_deformation.isChecked():
                self.results_dock.hide()
            self._status("Reaction diagram hidden")

    def _apply_reactions(self) -> None:
        comps = self.results_panel.reaction_components()
        if not comps:
            self.viewport.clear_reactions()
            self._status("Select at least one reaction component.")
            return
        scenario = (self.results_panel.reaction_scenario()
                    or self.results_scenario
                    or self.scenario_combo.currentText())
        res = self._ensure_static_results(scenario)
        if res is None:
            self.a_reactions.blockSignals(True)
            self.a_reactions.setChecked(False)
            self.a_reactions.blockSignals(False)
            return
        self.results_dock.show()
        self.results_dock.raise_()
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        self.viewport.set_reaction_results(
            res, res.scenario, comps,
            self.results_panel.reaction_scale_value(),
            self.results_panel.reaction_show_values(),
            self.results_panel.reaction_show_legend())
        self.a_reactions.blockSignals(True)
        self.a_reactions.setChecked(True)
        self.a_reactions.blockSignals(False)
        self.ribbon.set_current("Results")
        self._status(f"Reactions: {res.scenario} · {', '.join(comps)}")

    def _reaction_display_changed(self) -> None:
        if self.viewport.show_reactions and self.viewport.reaction_results is not None:
            self.viewport.reaction_values = self.results_panel.reaction_show_values()
            self.viewport.reaction_legend = self.results_panel.reaction_show_legend()
            self.viewport.update()

    def _results_dock_visibility(self, visible: bool) -> None:
        if visible:
            return
        deform_was = self.a_deformation.isChecked()
        diagram_was = self.a_beam_diagram.isChecked()
        for action in (self.a_beam_diagram, self.a_deformation,
                       self.a_reactions):
            action.blockSignals(True)
            action.setChecked(False)
            action.blockSignals(False)
        self.viewport.clear_diagrams()
        self.viewport.clear_reactions()
        if deform_was or diagram_was:
            self.viewport.show_deformed = False
            self.a_deformed.blockSignals(True)
            self.a_deformed.setChecked(False)
            self.a_deformed.blockSignals(False)

    def _refresh_mode_combo(self) -> None:
        if not hasattr(self, "mode_combo"):
            return
        current = self.viewport.mode_index if self.modal_results else 1
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        if self.modal_results and self.modal_results.modes:
            for m in self.modal_results.modes:
                self.mode_combo.addItem(
                    f"Mode {m.mode}   T = {fmt(m.period, 4)} s", m.mode)
            index = self.mode_combo.findData(current)
            self.mode_combo.setCurrentIndex(index if index >= 0 else 0)
            self.mode_combo.setEnabled(True)
        else:
            self.mode_combo.addItem("No modal results")
            self.mode_combo.setEnabled(False)
        self.mode_combo.blockSignals(False)

    def _clear_non_modal_overlays(self) -> None:
        """Clear static diagrams, reactions, and live-load overlays for modal view."""
        self.viewport.clear_diagrams()
        self.viewport.clear_reactions()
        for action in (self.a_beam_diagram, self.a_deformation,
                       self.a_reactions):
            action.blockSignals(True)
            action.setChecked(False)
            action.blockSignals(False)
        if hasattr(self, "results_dock"):
            self.results_dock.hide()

    def _mode_selected(self, index: int) -> None:
        if self.modal_results is None or index < 0:
            return
        self._clear_non_modal_overlays()
        mode = self.mode_combo.itemData(index) or (index + 1)
        self.viewport.set_modal_results(self.modal_results, int(mode))
        self.viewport.show_deformed = True
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        self.a_deformed.blockSignals(True)
        self.a_deformed.setChecked(True)
        self.a_deformed.blockSignals(False)
        if self.a_animate.isChecked():
            self.viewport.start_animation()
        else:
            self.viewport.stop_animation()
        period = next((m.period for m in self.modal_results.modes
                       if m.mode == int(mode)), 0.0)
        self._status(f"Mode {mode}  ·  T = {fmt(period, 4)} s")

    def _refresh_results_panel(self) -> None:
        self._refresh_mode_combo()
        if not hasattr(self, "results_panel"):
            return
        names = self.project.scenario_names()
        self.results_panel.set_scenarios(names)
        current = self.results_scenario or self.scenario_combo.currentText()
        if current in names:
            self.results_panel.set_current_scenario(current)
        if not names:
            self.results_panel.set_note("Create a load case first.")
        elif not self.static_cache:
            self.results_panel.set_note("A case is solved automatically when you "
                                        "apply a diagram or deformation.")

    def _ensure_static_results(self, scenario: str) -> Optional[opsgen.StaticResults]:
        if not scenario:
            self._warn("Select a load case or combination first.")
            return None
        if scenario in self.static_cache:
            return self.static_cache[scenario]
        if not self.project.elements:
            self._warn("The model has no elements.")
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self._status(f"Solving {scenario}…")
        try:
            res = opsgen.run_static(self.project, scenario)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._log(f"✖ Analysis '{scenario}' failed: {exc}")
            QMessageBox.critical(self, "Analysis failed", str(exc))
            self._status(f"Analysis '{scenario}' failed")
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.static_cache[scenario] = res
        self._log(f"Results cached for '{scenario}' (max |u| = "
                  f"{fmt(UNITS.length(res.max_disp), 4)} {UNITS.length_unit}).")
        self._set_locked(True)
        return res

    def _apply_beam_diagram(self) -> None:
        comps = self.results_panel.components()
        if not comps:
            self._status("Select at least one diagram component (Fx, Vy, Vz, Mx, My, Mz).")
            return
        scenario = self.results_panel.diagram_scenario() or self.scenario_combo.currentText()
        modes = getattr(self, "live_load_modes", {})
        if scenario in modes and getattr(self, "live_load_results", None) is not None:
            self._apply_live_load_envelope(scenario)
            return
        res = self._ensure_static_results(scenario)
        if res is None:
            return
        self.results_dock.show()
        self.results_dock.raise_()
        self.viewport.set_diagrams(
            res, scenario, comps, self.results_panel.diagram_scale_value(),
            self.results_panel.diagram_show_values(),
            self.results_panel.diagram_has_fill())
        if self.results_panel.diagram_overlay_deform():
            self.viewport.set_static_results(res)
            self._apply_scale()
            self.viewport.show_deformed = True
            self.a_deformed.blockSignals(True)
            self.a_deformed.setChecked(True)
            self.a_deformed.blockSignals(False)
        else:
            self.viewport.show_deformed = False
            self.a_deformed.blockSignals(True)
            self.a_deformed.setChecked(False)
            self.a_deformed.blockSignals(False)
        self.a_beam_diagram.blockSignals(True)
        self.a_beam_diagram.setChecked(True)
        self.a_beam_diagram.blockSignals(False)
        self.ribbon.set_current("Results")
        self.results_dock.raise_()
        self._status(f"Beam diagrams: {scenario} · {', '.join(comps)}")
        self.viewport.update()

    def _apply_live_load_envelope(self, scenario: str) -> None:
        modes = getattr(self, "live_load_modes", {})
        result = getattr(self, "live_load_results", None)
        geometry = getattr(self, "live_load_geometry", None)
        if result is None or scenario not in modes:
            return
        if geometry is None or len(geometry.get("points", [])) < 2:
            self._status("No beam-chain geometry available for the live-load envelope.")
            return
        case_key, mode = modes[scenario]
        case = result.cases.get(case_key)
        if case is None:
            return
        comps = [c for c in self.results_panel.components()
                 if c in ("My", "Vz", "Vy")]
        if not comps:
            comps = ["My", "Vz"]
        envelopes = {}
        if "My" in comps:
            envelopes["My"] = [(p.x, p.max, p.min) for p in case.moment]
        if "Vz" in comps or "Vy" in comps:
            envelopes["Vz"] = [(p.x, p.max, p.min) for p in case.shear]
        if not envelopes:
            envelopes["My"] = [(p.x, p.max, p.min) for p in case.moment]
        self.viewport.set_live_load_envelopes(
            envelopes,
            geometry["points"], scenario, mode,
            self.results_panel.diagram_scale_value(),
            self.results_panel.diagram_has_fill())
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        self.viewport.show_deformed = False
        self.a_deformed.blockSignals(True)
        self.a_deformed.setChecked(False)
        self.a_deformed.blockSignals(False)
        self.a_beam_diagram.blockSignals(True)
        self.a_beam_diagram.setChecked(True)
        self.a_beam_diagram.blockSignals(False)
        self.ribbon.set_current("Results")
        self.results_dock.show()
        self.results_dock.raise_()
        self._status(f"Live-load envelope: {scenario} · "
                     f"{', '.join(envelopes)}")

    def _deformation_values_changed(self, checked: bool) -> None:
        self.viewport.show_deformation_values = bool(checked)
        self.viewport.update()

    def _apply_deformation(self) -> None:
        scenario = self.results_panel.deformation_scenario() or self.scenario_combo.currentText()
        res = self._ensure_static_results(scenario)
        if res is None:
            return
        self.results_dock.show()
        self.results_dock.raise_()
        self.viewport.clear_diagrams()
        self.a_beam_diagram.blockSignals(True)
        self.a_beam_diagram.setChecked(False)
        self.a_beam_diagram.blockSignals(False)
        self.viewport.set_static_results(res)
        scale = self.results_panel.deformation_scale_value()
        self.viewport.deformed_scale = scale if scale > 0 else None
        self.scale_spin.blockSignals(True)
        self.scale_spin.setValue(scale)
        self.scale_spin.blockSignals(False)
        self.viewport.show_deformed = True
        self.viewport.show_deformation_values = (
            self.results_panel.deformation_show_values())
        self.a_deformed.blockSignals(True)
        self.a_deformed.setChecked(True)
        self.a_deformed.blockSignals(False)
        self.a_deformation.blockSignals(True)
        self.a_deformation.setChecked(True)
        self.a_deformation.blockSignals(False)
        self.ribbon.set_current("Results")
        self.results_dock.raise_()
        self._status(f"Deformed shape: {scenario}")

    def _scenario_changed(self, text: str) -> None:
        if not text:
            return
        self.viewport.set_load_scenario(text)
        self.viewport.load_filter_active = False
        self.viewport.display_cases.clear()
        self.project.settings["last_case"] = text
        if hasattr(self, "results_panel"):
            self.results_panel.set_current_scenario(text)
        self._refresh_tree()
        self.viewport.update()

    # ==================================================================== docks
    def _make_docks(self) -> None:
        # ---- model tree ------------------------------------------------
        self.tree = ModelTree()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setMinimumWidth(220)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragOnly)
        self.tree.setDefaultDropAction(Qt.CopyAction)
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

        # ---- draw element side panel ---------------------------------
        self.draw_panel = QWidget()
        draw_lay = QVBoxLayout(self.draw_panel)
        draw_lay.setContentsMargins(8, 8, 8, 8)
        draw_lay.addWidget(dialogs.hint(
            "Click a start node, then an end node. The end node becomes the "
            "next start. Right-click, Esc or Finish ends the tool."))
        draw_form = QFormLayout()
        self.draw_material = QComboBox()
        self.draw_section = QComboBox()
        draw_form.addRow("Material", self.draw_material)
        draw_form.addRow("Section", self.draw_section)
        draw_lay.addLayout(draw_form)
        finish = QPushButton("Finish  (Esc / right-click)")
        finish.clicked.connect(
            lambda: self.a_draw_element.setChecked(False))
        draw_lay.addWidget(finish)
        self.draw_info = QLabel("")
        self.draw_info.setWordWrap(True)
        self.draw_info.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        draw_lay.addWidget(self.draw_info)
        draw_lay.addStretch(1)
        draw_dock = QDockWidget("Draw Element", self)
        draw_dock.setObjectName("draw_dock")
        draw_dock.setWidget(self.draw_panel)
        draw_dock.setMinimumWidth(230)
        self.addDockWidget(Qt.LeftDockWidgetArea, draw_dock)
        self.splitDockWidget(self.model_dock, draw_dock, Qt.Vertical)
        draw_dock.hide()
        self.draw_dock = draw_dock
        self.viewport.elementDrawRequested.connect(self._draw_element_between)
        self.viewport.drawModeCancelled.connect(self._cancel_draw_mode)

        # ---- structure / boundary groups -------------------------------
        self.groups_tree = QTreeWidget()
        self.groups_tree.setHeaderHidden(True)
        self.groups_tree.setColumnCount(1)
        self.groups_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.groups_tree.itemDoubleClicked.connect(self._group_tree_double)
        self.groups_tree.itemSelectionChanged.connect(self._group_selection_changed)
        self.groups_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.groups_tree.customContextMenuRequested.connect(
            self._group_tree_menu)
        groups_panel = QWidget()
        groups_lay = QVBoxLayout(groups_panel)
        groups_lay.setContentsMargins(6, 6, 6, 6)
        group_buttons = QHBoxLayout()
        self.new_structure_group_btn = QPushButton("Structure +")
        self.new_structure_group_btn.clicked.connect(self.new_structure_group)
        self.new_boundary_group_btn = QPushButton("Boundary +")
        self.new_boundary_group_btn.clicked.connect(self.new_boundary_group)
        self.add_group_members_btn = QPushButton("Add selection")
        self.add_group_members_btn.clicked.connect(self.add_selected_to_group)
        self.add_group_members_btn.setEnabled(False)
        group_buttons.addWidget(self.new_structure_group_btn)
        group_buttons.addWidget(self.new_boundary_group_btn)
        groups_lay.addLayout(group_buttons)
        groups_lay.addWidget(self.add_group_members_btn)
        groups_lay.addWidget(dialogs.hint(
            "Select elements or nodes, create a group, then use the tree to "
            "recall each selection. Right-click a group to add, rename or delete."))
        groups_lay.addWidget(self.groups_tree, 1)
        groups_dock = QDockWidget("Groups", self)
        groups_dock.setObjectName("groups_dock")
        groups_dock.setWidget(groups_panel)
        groups_dock.setMinimumWidth(240)
        self.addDockWidget(Qt.RightDockWidgetArea, groups_dock)
        self.groups_dock = groups_dock

        # ---- properties ------------------------------------------------
        self.props = QStackedWidget()
        self.props.setMinimumWidth(280)
        self._build_props()
        dock2 = QDockWidget("Properties", self)
        dock2.setObjectName("props_dock")
        dock2.setWidget(self.props)
        dock2.setMinimumWidth(290)
        self.addDockWidget(Qt.RightDockWidgetArea, dock2)
        self.splitDockWidget(self.groups_dock, dock2, Qt.Vertical)
        self.props_dock = dock2

        # ---- results sidebar -------------------------------------------
        self.results_panel = ResultsPanel(self)
        self.results_panel.diagramRequested.connect(self._apply_beam_diagram)
        self.results_panel.deformationRequested.connect(self._apply_deformation)
        self.results_panel.reactionRequested.connect(self._apply_reactions)
        self.results_panel.reactionDisplayChanged.connect(
            self._reaction_display_changed)
        self.results_panel.deform_values.toggled.connect(
            self._deformation_values_changed)
        dock4 = QDockWidget("Results View", self)
        dock4.setObjectName("results_dock")
        dock4.setWidget(self.results_panel)
        dock4.setMinimumWidth(280)
        self.addDockWidget(Qt.RightDockWidgetArea, dock4)
        self.tabifyDockWidget(dock2, dock4)
        dock4.hide()
        dock2.hide()
        self.results_dock = dock4
        self.results_dock.visibilityChanged.connect(self._results_dock_visibility)

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
                             (self.groups_dock, self.a_groups_visible),
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
            "2. <b>E</b> batch elements, <b>Draw Element</b> for node-to-node<br>"
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
        self.research_label = QLabel("RESEARCH USE ONLY")
        self.research_label.setStyleSheet(
            "color:#b45309; font-weight:700; padding:0 10px;")
        self.research_label.setToolTip(
            "Early alpha; results are not fully verified. Not for real-world "
            "commercial work or public-safety decisions")
        sb.addPermanentWidget(self.research_label)
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
        self._refresh_group_tree()
        self._refresh_scenarios()
        self._refresh_props()
        self._refresh_results_panel()
        self._refresh_draw_combos()
        self.viewport.hidden_nodes.intersection_update(self.project.nodes)
        self.viewport.hidden_elements.intersection_update(self.project.elements)
        self._update_title()
        self.viewport.update()

    def _refresh_draw_combos(self) -> None:
        if not hasattr(self, "draw_material"):
            return
        for combo, items, empty in (
                (self.draw_material, self.project.materials, "No materials"),
                (self.draw_section, self.project.sections, "No sections")):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for tag, item in sorted(items.items()):
                combo.addItem(f"{tag}   {item.name}", tag)
            if combo.count() == 0:
                combo.addItem(empty, 0)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self.draw_info.setText(
            f"{len(self.project.materials)} material(s), "
            f"{len(self.project.sections)} section(s).")

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
                                   "Drag onto selected elements to assign. "
                                   "Right-click: delete.")
            elif kind == "hinge":
                item.setToolTip(0, "Double-click: open the hinge assignment table. "
                                   "Drag onto selected beam elements to assign.")
            elif kind == "support_preset":
                item.setToolTip(0, "Drag onto selected nodes to apply this support.")
            parent.addChild(item)
            return item

        g_mat = group("Materials", "materials", len(p.materials))
        used_materials = {e.mat for e in p.elements.values()}
        for m in p.materials.values():
            item = add_child(g_mat, f"{m.tag}   {m.name}   ({m.kind})",
                             "material", m.tag)
            if m.tag not in used_materials:
                item.setForeground(0, QBrush(QColor(theme.ACCENT)))
                item.setToolTip(0, "Unused material - no element references it.")
        g_sec = group("Sections", "sections", len(p.sections))
        used_sections = {e.sec for e in p.elements.values()}
        for s in p.sections.values():
            item = add_child(g_sec, f"{s.tag}   {s.name}   ({s.shape})",
                             "section", s.tag)
            if s.tag not in used_sections:
                item.setForeground(0, QBrush(QColor(theme.ACCENT)))
                item.setToolTip(0, "Unused section - no element references it.")
        g_hinge = group("Hinges", "hinges", len(p.hinge_defs))
        hinge_use = {}
        for element, hinge in p.hinge_assignments.items():
            hinge_use[hinge] = hinge_use.get(hinge, 0) + 1
        for h in sorted(p.hinge_defs.values(), key=lambda d: d.tag):
            count = hinge_use.get(h.tag, 0)
            suffix = f"{count} el." if count else "unassigned"
            item = add_child(
                g_hinge, f"H{h.tag}   {h.name}   ({h.material}, {suffix})",
                "hinge", h.tag)
            item.setToolTip(0, "Double-click: edit the hinge library.")
            if count == 0:
                item.setForeground(0, QBrush(QColor(theme.ACCENT)))

        b = group("Boundary", "boundary")
        g_sup = group("Supports", "supports",
                      sum(1 for n in p.nodes.values() if any(n.support)), b)
        support_groups: Dict[str, List[int]] = {}
        for n in p.nodes.values():
            if any(n.support):
                support_groups.setdefault(n.support_code(), []).append(n.tag)
        for code, tags in sorted(support_groups.items()):
            pattern = ",".join(code)
            item = add_child(g_sup, f"{pattern} ({len(tags)})",
                             "support_group", tuple(sorted(tags)))
            item.setToolTip(0, f"{len(tags)} node(s): {sorted(tags)}\n"
                               "Double-click to select them in the model.")
        g_spring = group("Point Springs", "springs", len(p.springs), b)
        for s in sorted(p.springs.values(), key=lambda item: item.tag):
            label = SPRING_DOFS[s.dof - 1] if 1 <= s.dof <= 6 else "?"
            add_child(g_spring,
                      f"S{s.tag}   node {s.node}   {label}   ({s.kind})",
                      "spring", s.tag)
        g_constraint = group("Constraints", "constraints", len(p.constraints), b)
        labels = {"rigid_beam": "rigid beam", "rigid_bar": "rigid bar",
                  "equal_dof": "equalDOF", "rigid_diaphragm": "diaphragm"}
        for c in sorted(p.constraints.values(), key=lambda item: item.tag):
            add_child(g_constraint,
                      f"C{c.tag}   {labels.get(c.kind, c.kind)}   "
                      f"{c.master} -> {len(c.slaves)} node(s)",
                      "constraint", c.tag)
        g_constraint.setToolTip(0, "Right-click a constraint to delete it.")
        g_lane = group("Traffic Lanes", "lanes", len(p.lanes), b)
        for lane in sorted(p.lanes.values(), key=lambda item: item.tag):
            add_child(
                g_lane,
                f"L{lane.tag}   {lane.name}   "
                f"x {lane.start[0]/1000:g}->{lane.end[0]/1000:g} m   "
                f"shift {lane.offset/1000:+g} m",
                "lane", lane.tag)
        g_lane.setToolTip(0, "Double-click: edit lane start/end and lateral shift.")

        ld = group("Loads", "loads")
        g_cases = group("Load Cases", "cases", len(p.cases), ld)
        for c in p.cases.values():
            n_el = sum(1 for load in p.elem_loads if load.case == c.name)
            n_nd = sum(1 for load in p.nodal_loads if load.case == c.name)
            sw = p.self_weight.get(c.name, 0.0)
            item = add_child(g_cases, f"{c.name}   ({c.kind})", "case", c.name)
            item.setToolTip(0, f"{n_el} element load(s), {n_nd} nodal load(s)"
                               + (f", self weight ×{fmt(sw, 3)}" if abs(sw) > 1e-12 else "")
                               + "\nDouble-click: select loaded elements"
                                 "\nRight-click: display, undisplay, table, delete")
            if self.viewport.load_filter_active and c.name in self.viewport.display_cases:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            if n_el == 0 and n_nd == 0 and abs(sw) < 1e-12:
                item.setForeground(0, QBrush(QColor(theme.ACCENT)))
                item.setToolTip(0, "Unused load case - it has no loads.")
        g_sw = group("Self Weight", "self_weight", len(p.self_weight), ld)
        for case, factor in p.self_weight.items():
            add_child(g_sw, f"{case}   factor {fmt(factor, 3)}")

        g_combo = group("Load Combinations", "combos", len(p.combos))
        for c in p.combos.values():
            add_child(g_combo, f"{c.name}   ({c.kind})", "combo", c.name)

        self.tree.expandAll()
        self.tree.blockSignals(False)

    # ------------------------------------------------- structure/boundary groups
    def _group_map(self, kind: str) -> Dict[str, List[int]]:
        if kind == "structure":
            return self.project.structure_groups
        return self.project.boundary_groups

    def _group_member_tags(self, kind: str) -> List[int]:
        return sorted(self.viewport.sel_elements if kind == "structure"
                      else self.viewport.sel_nodes)

    def _next_group_name(self, kind: str) -> str:
        base = "Structure" if kind == "structure" else "Boundary"
        names = {name.casefold() for name in self._group_map(kind)}
        index = 1
        while f"{base} {index}".casefold() in names:
            index += 1
        return f"{base} {index}"

    def new_structure_group(self) -> None:
        self._new_group("structure")

    def new_boundary_group(self) -> None:
        self._new_group("boundary")

    def _new_group(self, kind: str) -> None:
        title = "Structure" if kind == "structure" else "Boundary"
        noun = "elements" if kind == "structure" else "nodes"
        if not self._group_member_tags(kind):
            self._warn(f"Select one or more {noun} first, then create the group.")
            return
        name, ok = QInputDialog.getText(
            self, f"New {title} Group", "Group name:",
            text=self._next_group_name(kind))
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if any(existing.casefold() == name.casefold()
               for existing in self._group_map(kind)):
            self._warn(f"A {title.lower()} group named '{name}' already exists.")
            return
        self._create_group(kind, name, self._group_member_tags(kind))

    def _create_group(self, kind: str, name: str, tags) -> None:
        source = (self.project.elements if kind == "structure"
                  else self.project.nodes)
        valid = sorted({int(tag) for tag in tags if int(tag) in source})
        if not valid:
            self._warn("No valid members selected for the group.")
            return
        self._group_map(kind)[name] = valid
        label = "structure" if kind == "structure" else "boundary"
        self._commit(f"Created {label} group {name}")
        self._select_group(kind, name)

    def add_selected_to_group(self) -> None:
        current = self._current_group()
        if current is None:
            self._warn("Select a structure or boundary group in the tree first.")
            return
        self._add_selection_to_group(*current)

    def _add_selection_to_group(self, kind: str, name: str) -> None:
        groups = self._group_map(kind)
        if name not in groups:
            self._warn(f"The {kind} group '{name}' no longer exists.")
            return
        tags = self._group_member_tags(kind)
        noun = "elements" if kind == "structure" else "nodes"
        if not tags:
            self._warn(f"Select one or more {noun} first.")
            return
        merged = sorted(set(groups[name]) | set(tags))
        if merged == groups[name]:
            self._status(f"{name} already contains the selected {noun}.")
            return
        groups[name] = merged
        self._commit(f"Added {len(tags)} {noun} to {kind} group {name}")

    def _current_group(self):
        item = self.groups_tree.currentItem()
        data = item.data(0, Qt.UserRole) if item is not None else None
        if data and data[0] in ("structure", "boundary") and data[1]:
            return data[0], data[1]
        return None

    def _group_selection_changed(self) -> None:
        self.add_group_members_btn.setEnabled(self._current_group() is not None)

    def _refresh_group_tree(self) -> None:
        if not hasattr(self, "groups_tree"):
            return
        self.groups_tree.blockSignals(True)
        self.groups_tree.clear()
        font = QFont("Segoe UI", 9, QFont.Bold)
        for kind, title in (("structure", "Structure Groups"),
                            ("boundary", "Boundary Groups")):
            groups = self._group_map(kind)
            root = QTreeWidgetItem([f"{title}   ({len(groups)})"])
            root.setData(0, Qt.UserRole, (f"{kind}_root", None))
            root.setFont(0, font)
            root.setForeground(0, QBrush(QColor(theme.ACCENT_DARK)))
            for name in sorted(groups, key=str.casefold):
                tags = groups[name]
                item = QTreeWidgetItem([f"{name}   ({len(tags)} members)"])
                item.setData(0, Qt.UserRole, (kind, name))
                preview = ", ".join(str(tag) for tag in tags[:24])
                if len(tags) > 24:
                    preview += ", ..."
                item.setToolTip(
                    0, f"{len(tags)} member(s): {preview}\n"
                       "Double-click to select the group in the model. "
                       "Right-click to add, rename or delete.")
                root.addChild(item)
            if not groups:
                empty = QTreeWidgetItem(["No groups defined"])
                empty.setFlags(Qt.ItemIsEnabled)
                root.addChild(empty)
            root.setExpanded(True)
            self.groups_tree.addTopLevelItem(root)
        self.groups_tree.expandAll()
        self.groups_tree.blockSignals(False)
        self._group_selection_changed()

    def _group_tree_double(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, name = data
        if kind in ("structure", "boundary") and name:
            self._select_group(kind, name)

    def _select_group(self, kind: str, name: str) -> None:
        tags = self._group_map(kind).get(name, [])
        if not tags:
            self._status(f"The {kind} group '{name}' is empty.")
            return
        if kind == "structure":
            self.viewport.select_elements(tags)
        else:
            self.viewport.select_nodes(tags)
        self.viewport.fit_selection()
        noun = "element" if kind == "structure" else "node"
        self._status(f"Selected {len(tags)} {noun}(s) from {kind} group {name}")

    def _rename_group(self, kind: str, name: str) -> None:
        groups = self._group_map(kind)
        if name not in groups:
            return
        title = "Structure" if kind == "structure" else "Boundary"
        new_name, ok = QInputDialog.getText(
            self, f"Rename {title} Group", "Group name:", text=name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == name:
            return
        if any(existing.casefold() == new_name.casefold()
               for existing in groups):
            self._warn(f"A {title.lower()} group named '{new_name}' already exists.")
            return
        groups[new_name] = groups.pop(name)
        self._commit(f"Renamed {kind} group {name} to {new_name}")

    def _delete_group(self, kind: str, name: str) -> None:
        groups = self._group_map(kind)
        if name not in groups:
            return
        answer = QMessageBox.question(
            self, "Delete Group",
            f"Delete the {kind} group '{name}'?\n\n"
            "This only removes the group; model nodes and elements are kept.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        groups.pop(name, None)
        self._commit(f"Deleted {kind} group {name}")

    def _group_tree_menu(self, pos) -> None:
        item = self.groups_tree.itemAt(pos)
        data = item.data(0, Qt.UserRole) if item is not None else None
        menu = QMenu(self)
        if data and data[0] in ("structure", "boundary") and data[1]:
            kind, name = data
            menu.addAction("Select members", lambda: self._select_group(kind, name))
            menu.addAction("Add current selection",
                           lambda: self._add_selection_to_group(kind, name))
            menu.addSeparator()
            menu.addAction("Rename...", lambda: self._rename_group(kind, name))
            menu.addAction("Delete...", lambda: self._delete_group(kind, name))
            menu.addSeparator()
        if data and data[0] == "structure_root":
            menu.addAction("New structure group from selection",
                           self.new_structure_group)
        elif data and data[0] == "boundary_root":
            menu.addAction("New boundary group from selection",
                           self.new_boundary_group)
        else:
            menu.addAction("New structure group from selection",
                           self.new_structure_group)
            menu.addAction("New boundary group from selection",
                           self.new_boundary_group)
        menu.exec(self.groups_tree.viewport().mapToGlobal(pos))

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
        elif key == "support_group":
            self.viewport.select_nodes(list(tag))
            self._status(f"Selected {len(tag)} node(s) with this support")
        elif key == "hinge":
            self._select_hinge_elements(tag)

    def _tree_double(self, item: QTreeWidgetItem, _col: int) -> None:
        data_items = []
        selected = self.tree.selectedItems()
        if item not in selected:
            selected = [item]
        for selected_item in selected:
            data = selected_item.data(0, Qt.UserRole)
            if data:
                data_items.append(data)
        if not data_items:
            return
        keys = {key for key, _tag in data_items}
        if keys <= {"material", "section"}:
            self._select_elements_using_items(data_items)
            return
        if keys == {"case"}:
            self._select_cases([tag for _key, tag in data_items if tag])
            return
        if keys == {"hinge"}:
            self.edit_hinge_defs()
            return
        if keys == {"support_group"}:
            tags = sorted({tag for _key, group in data_items if group
                           for tag in group})
            if tags:
                self.viewport.select_nodes(tags)
                self.viewport.fit_selection()
                self._status(f"Selected {len(tags)} supported node(s)")
            return
        key, tag = data_items[0]
        if tag is not None:
            if key in ("material", "section"):
                self._select_elements_using(key, tag)
            elif key == "case":
                if (tag in getattr(self, "live_load_modes", {})
                        and getattr(self, "live_load_results", None) is not None):
                    self.results_panel.set_current_scenario(str(tag))
                    self._apply_beam_diagram()
                else:
                    self._select_case_elements(tag)
            elif key == "hinge":
                self.edit_hinge_defs()
            elif key == "lane":
                self.lane_definitions()
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
            "hinges": self.edit_hinge_defs,
            "cases": self.load_cases,
            "nodal_loads": lambda: self.open_tables(6),
            "element_loads": lambda: self.open_tables(7),
            "self_weight": self.self_weight,
            "combos": self.combinations,
        }
        fn = actions.get(key)
        if fn:
            fn()

    def _select_elements_using_items(self, data_items) -> None:
        tags = set()
        labels = []
        for kind, tag in data_items:
            if tag is None:
                continue
            if kind == "material":
                tags.update(e.tag for e in self.project.elements.values()
                            if e.mat == tag)
                labels.append(f"material {tag}")
            elif kind == "section":
                tags.update(e.tag for e in self.project.elements.values()
                            if e.sec == tag)
                labels.append(f"section {tag}")
        if not tags:
            self._status("No elements use the selected items")
            return
        self.viewport.select_elements(sorted(tags))
        self.viewport.fit_selection()
        self._status(f"Selected {len(tags)} element(s) using "
                     + ", ".join(labels))

    def _select_cases(self, cases) -> None:
        element_tags = set()
        node_tags = set()
        for case in cases:
            element_tags.update(load.elem for load in self.project.elem_loads
                                if load.case == case
                                and load.elem in self.project.elements)
            if abs(self.project.self_weight.get(case, 0.0)) > 1e-12:
                element_tags.update(self.project.elements)
            node_tags.update(load.node for load in self.project.nodal_loads
                             if load.case == case and load.node in self.project.nodes)
        if element_tags:
            self.viewport.select_elements(sorted(element_tags))
            self._status(f"Selected {len(element_tags)} element(s) carrying "
                         + ", ".join(cases))
        elif node_tags:
            self.viewport.select_nodes(sorted(node_tags))
            self._status(f"Selected {len(node_tags)} node(s) carrying "
                         + ", ".join(cases))
        else:
            self._status("The selected load cases have no applied loads")

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

    def _select_hinge_elements(self, tag) -> None:
        tags = sorted(e for e, hinge in self.project.hinge_assignments.items()
                      if hinge == tag and e in self.project.elements)
        if not tags:
            self._status("This hinge is not assigned to any element")
            return
        self.viewport.select_elements(tags)
        self.viewport.fit_selection()
        self._status(f"Selected {len(tags)} element(s) using hinge {tag}")

    def _apply_tree_drop(self, kind: str, value) -> None:
        """Apply a material/section/hinge/support dragged from the model tree."""
        if self.model_locked:
            self._warn("The model is locked. Press Ctrl+L to unlock before editing.")
            return
        if kind in ("material", "section", "hinge"):
            tags = sorted(self.viewport.sel_elements)
            if not tags:
                self._warn("Select the target elements first, then drag onto the view.")
                return
            if kind == "material" and int(value) not in self.project.materials:
                self._warn(f"Material {value} no longer exists.")
                return
            if kind == "section" and int(value) not in self.project.sections:
                self._warn(f"Section {value} no longer exists.")
                return
            if kind == "hinge" and int(value) not in self.project.hinge_defs:
                self._warn(f"Hinge {value} no longer exists.")
                return
            applied = skipped = 0
            for tag in tags:
                element = self.project.elements.get(tag)
                if element is None:
                    continue
                if kind == "material":
                    element.mat = int(value)
                elif kind == "section":
                    element.sec = int(value)
                else:
                    if element.kind != "beam":
                        skipped += 1
                        continue
                    self.project.hinge_assignments[int(tag)] = int(value)
                applied += 1
            if not applied:
                self._warn("No compatible selected elements for this item.")
                return
            label = f"Assigned {kind} {value} to {applied} element(s)"
            if skipped:
                label += f" ({skipped} non-beam skipped)"
            self._commit(label)
            return
        if kind == "support_preset":
            flags = SUPPORT_PRESETS.get(str(value))
            if flags is None:
                return
            nodes = sorted(self.viewport.sel_nodes)
            if not nodes:
                self._warn("Select the target nodes first, then drag onto the view.")
                return
            for tag in nodes:
                node = self.project.nodes.get(tag)
                if node is not None:
                    node.support = list(flags)
            self._commit(f"Applied {value} support to {len(nodes)} node(s)")

    def _tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        selected = self.tree.selectedItems()
        if item not in selected:
            selected = [item]
        data_items = [selected_item.data(0, Qt.UserRole)
                      for selected_item in selected]
        data_items = [entry for entry in data_items if entry]
        keys = {key for key, _tag in data_items}
        kind, tag = data
        menu = QMenu(self)
        if tag is None:
            self._build_group_menu(menu, kind)
            if menu.actions():
                menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if keys == {"support_group"}:
            groups = [group for _key, group in data_items if group]
            tags = sorted({node for group in groups for node in group})
            select = menu.addAction("Select nodes")
            select.triggered.connect(lambda: self.viewport.select_nodes(tags))
            table = menu.addAction("Supports table")
            table.triggered.connect(lambda: self.open_tables(1))
            clear = menu.addAction("Clear supports")
            clear.setEnabled(not self.model_locked)
            clear.triggered.connect(lambda: self._clear_support_nodes(tags))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if keys <= {"material", "section"}:
            select = menu.addAction("Select elements using selected items")
            select.triggered.connect(
                lambda: self._select_elements_using_items(data_items))
            menu.addSeparator()
            delete = menu.addAction("Delete selected")
            delete.setEnabled(not self.model_locked)
            delete.triggered.connect(
                lambda: self._delete_tree_entities(data_items))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if keys == {"case"}:
            cases = [case for _key, case in data_items if case]
            display = menu.addAction("Display")
            display.triggered.connect(
                lambda: [self._display_load_case(case, True) for case in cases])
            undisplay = menu.addAction("Undisplay")
            undisplay.triggered.connect(
                lambda: [self._display_load_case(case, False) for case in cases])
            menu.addSeparator()
            table = menu.addAction("Table.")
            table.setEnabled(not self.model_locked)
            table.triggered.connect(lambda: self._open_case_table(cases[0]))
            delete = menu.addAction("Delete")
            delete.setEnabled(not self.model_locked)
            delete.triggered.connect(lambda: self._delete_load_case(cases[0]))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if kind in ("spring", "constraint"):
            delete = menu.addAction("Delete")
            delete.setEnabled(not self.model_locked)
            delete.triggered.connect(lambda: self._delete_tree_entity(kind, tag))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if kind not in ("material", "section"):
            return
        select = menu.addAction("Select elements using this")
        select.triggered.connect(lambda: self._select_elements_using(kind, tag))
        menu.addSeparator()
        delete = menu.addAction(f"Delete {kind} {tag}")
        delete.setEnabled(not self.model_locked)
        delete.triggered.connect(lambda: self._delete_tree_entity(kind, tag))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _clear_support_nodes(self, tags) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        changed = 0
        for tag in tags:
            node = self.project.nodes.get(tag)
            if node is not None and any(node.support):
                node.support = [False] * 6
                changed += 1
        if changed:
            self._commit(f"Cleared {changed} support(s)")
            self.viewport.select_nodes(tags)

    def _delete_tree_entities(self, data_items) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        targets = [(kind, tag) for kind, tag in data_items
                   if tag is not None and kind in ("material", "section")]
        if not targets:
            return
        blocked = []
        for kind, tag in targets:
            if kind == "material":
                used = [e.tag for e in self.project.elements.values() if e.mat == tag]
                if tag not in self.project.materials:
                    continue
                if used:
                    blocked.append(f"material {tag} ({len(used)} elements)")
            else:
                used = [e.tag for e in self.project.elements.values() if e.sec == tag]
                if tag not in self.project.sections:
                    continue
                if used:
                    blocked.append(f"section {tag} ({len(used)} elements)")
        if blocked:
            self._warn("Cannot delete items in use:\n" + "\n".join(blocked))
            return
        if QMessageBox.question(self, "Delete items",
                                f"Delete {len(targets)} selected item(s)?") != QMessageBox.Yes:
            return
        removed = 0
        for kind, tag in targets:
            collection = (self.project.materials if kind == "material"
                          else self.project.sections)
            if tag in collection and len(collection) > 1:
                del collection[tag]
                removed += 1
        if removed:
            self._commit(f"Deleted {removed} model item(s)")

    def _build_group_menu(self, menu: QMenu, kind: str) -> None:
        def add(text: str, slot) -> None:
            action = menu.addAction(text)
            action.triggered.connect(slot)

        if kind == "nodes":
            add("Open node table", lambda: self.open_tables(0))
        elif kind == "elements":
            add("Open element table", lambda: self.open_tables(2))
        elif kind == "materials":
            add("Add new material...", lambda: self.materials(add_new=True))
            add("Open material library", self.materials)
            add("Open material table", lambda: self.open_tables(3))
        elif kind == "sections":
            add("Add new section...", lambda: self.sections(add_new=True))
            add("Open section library", self.sections)
            add("Open section table", lambda: self.open_tables(4))
        elif kind == "hinges":
            add("Add new hinge...", lambda: self.edit_hinge_defs(add_new=True))
            add("Open hinge library", self.edit_hinge_defs)
        elif kind == "supports":
            add("Assign supports...", self.assign_supports)
            add("Open supports table", lambda: self.open_tables(1))
        elif kind == "springs":
            add("Add point spring...", self.add_point_springs)
        elif kind == "constraints":
            add("Rigid link...", self.add_rigid_link)
            add("Equal DOF...", self.add_equal_dof)
            add("Rigid diaphragm...", self.add_diaphragm)
        elif kind == "cases":
            add("Add new load case...", lambda: self.load_cases(add_new=True))
            add("Open load case table", lambda: self.open_tables(5))
        elif kind == "self_weight":
            add("Set self weight...", self.self_weight)
        elif kind == "combos":
            add("Add new combination...", lambda: self.combinations(add_new=True))
            add("Open combination table", lambda: self.open_tables(8))

    def _select_case_elements(self, case: str) -> None:
        element_tags = sorted({load.elem for load in self.project.elem_loads
                               if load.case == case
                               and load.elem in self.project.elements})
        if abs(self.project.self_weight.get(case, 0.0)) > 1e-12:
            element_tags = sorted(set(element_tags) | set(self.project.elements))
        if element_tags:
            self.viewport.select_elements(element_tags)
            self._status(f"Selected {len(element_tags)} element(s) carrying load case {case}")
            return
        node_tags = sorted({load.node for load in self.project.nodal_loads
                            if load.case == case and load.node in self.project.nodes})
        if node_tags:
            self.viewport.select_nodes(node_tags)
            self._status(f"Selected {len(node_tags)} node(s) carrying load case {case}")
            return
        self._status(f"Load case {case} has no applied loads")

    def _display_load_case(self, case: str, show: bool) -> None:
        if show:
            if not self.viewport.load_filter_active:
                self.viewport.set_display_cases([])
            self.viewport.display_cases.add(case)
        else:
            if not self.viewport.load_filter_active:
                self.viewport.set_display_cases([])
            self.viewport.display_cases.discard(case)
        self.viewport.load_filter_active = True
        self.viewport.show_loads = bool(self.viewport.display_cases)
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(self.viewport.show_loads)
        self.a_loads_visible.blockSignals(False)
        self._refresh_tree()
        self.viewport.update()
        if self.viewport.display_cases:
            self._status("Displaying load case(s): "
                         + ", ".join(sorted(self.viewport.display_cases)))
        else:
            self._status("No load cases displayed")

    def _open_case_table(self, case: str) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        dlg = TablesDialog(self.project, self, case_filter=case)
        dlg.tabs.setCurrentWidget(dlg.page_eleload)
        if not dlg.exec() or dlg.result_project is None:
            return
        self._adopt(dlg.result_project)
        self._clear_results()
        self._commit(f"Edited element loads [{case}]")
        self.viewport.fit()

    def _delete_load_case(self, case: str) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        p = self.project
        n_el = sum(1 for load in p.elem_loads if load.case == case)
        n_nd = sum(1 for load in p.nodal_loads if load.case == case)
        if QMessageBox.question(
                self, "Delete load case",
                f"Delete load case {case} and its {n_el} element load(s) and "
                f"{n_nd} nodal load(s)?\nCombination references will be removed."
        ) != QMessageBox.Yes:
            return
        del p.cases[case]
        p.nodal_loads = [load for load in p.nodal_loads if load.case != case]
        p.elem_loads = [load for load in p.elem_loads if load.case != case]
        p.self_weight.pop(case, None)
        for combo in list(p.combos.values()):
            combo.factors = [(c, f) for c, f in combo.factors if c != case]
            if not combo.factors:
                del p.combos[combo.name]
        self.viewport.display_cases.discard(case)
        self.viewport.show_loads = bool(self.viewport.display_cases)
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(self.viewport.show_loads)
        self.a_loads_visible.blockSignals(False)
        self._commit(f"Deleted load case {case}")

    def _delete_tree_entity(self, kind: str, tag) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        if kind in ("spring", "constraint"):
            collection = (self.project.springs if kind == "spring"
                          else self.project.constraints)
            if tag not in collection:
                return
            noun = "point spring" if kind == "spring" else "constraint"
            if QMessageBox.question(self, f"Delete {noun}",
                                    f"Delete {noun} {tag}?") != QMessageBox.Yes:
                return
            del collection[tag]
            self._commit(f"Deleted {noun} {tag}")
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
            f"<tr><td>Point springs</td><td><b>{len(p.springs)}</b></td></tr>"
            f"<tr><td>Constraints</td><td><b>{len(p.constraints)}</b></td></tr>"
            f"<tr><td>Load cases</td><td><b>{len(p.cases)}</b></td></tr>"
            f"<tr><td>Nodal loads</td><td><b>{len(p.nodal_loads)}</b></td></tr>"
            f"<tr><td>Element loads</td><td><b>{len(p.elem_loads)}</b></td></tr>"
            f"<tr><td>Combinations</td><td><b>{len(p.combos)}</b></td></tr>"
            f"</table>")
        self._on_selection()

    def _on_selection(self) -> None:
        sel_n = self.viewport.sel_nodes
        sel_e = self.viewport.sel_elements
        self._sync_selection_boxes()
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
            if e.kind in DEVICE_KINDS:
                d = e.device or {}
                if e.kind == "bearing":
                    detail = (
                        f"Elastomeric bearing<br>"
                        f"kInit = {fmt(UNITS.dist(d.get('k_init', 0.0)), 3)} "
                        f"{UNITS.dist_unit}<br>"
                        f"qd = {fmt(UNITS.force(d.get('qd', 0.0)), 2)} "
                        f"{UNITS.force_unit}<br>"
                        f"Kv = {fmt(UNITS.dist(d.get('kv', 0.0)), 3)} "
                        f"{UNITS.dist_unit}")
                elif e.kind == "isolator":
                    detail = (
                        f"Lead-rubber isolator<br>"
                        f"Fy = {fmt(UNITS.force(d.get('fy', 0.0)), 2)} "
                        f"{UNITS.force_unit}<br>"
                        f"Gr = {fmt(UNITS.stress(d.get('gr', 0.0)), 4)} "
                        f"{UNITS.stress_unit}<br>"
                        f"D1 / D2 = {fmt(UNITS.length(d.get('d1', 0.0)), 1)} / "
                        f"{fmt(UNITS.length(d.get('d2', 0.0)), 1)} "
                        f"{UNITS.length_unit}")
                else:
                    detail = (
                        f"{'Bilinear oil' if d.get('type') == 'damper_oil' else 'Viscous'} damper<br>"
                        f"K_el = {fmt(UNITS.dist(d.get('k_el', 0.0)), 3)} "
                        f"{UNITS.dist_unit}<br>"
                        f"Cd = {fmt(float(d.get('cd', 0.0)), 4)}<br>"
                        f"alpha = {fmt(float(d.get('alpha', 0.0)), 3)}")
                self.el_info.setText(
                    f"Nodes {e.nodes}<br>Length "
                    f"{fmt(UNITS.length(self.project.element_length(e)), 1)} "
                    f"{UNITS.length_unit}<br>{detail}")
            else:
                self.el_info.setText(
                    f"Nodes {e.nodes}<br>Length {fmt(UNITS.length(self.project.element_length(e)), 1)} "
                    f"{UNITS.length_unit}<br>"
                    f"Section A = {fmt(UNITS.area(sec.A), 1)} {UNITS.area_unit}, "
                    f"Iy = {fmt(UNITS.inertia(sec.Iy), 1)}, "
                    f"Iz = {fmt(UNITS.inertia(sec.Iz), 1)} {UNITS.inertia_unit}")
            self.el_mat.setEnabled(e.kind not in DEVICE_KINDS)
            self.el_sec.setEnabled(e.kind not in DEVICE_KINDS)
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
    def _viewport_context_menu(self, kind: str, tag: int, pos) -> None:
        menu = QMenu(self)
        show = menu.addAction("Show details")
        if kind == "node":
            show.triggered.connect(lambda: self._show_node_details(tag))
            edit = menu.addAction("Edit node properties")
            edit.setEnabled(not self.model_locked)
            edit.triggered.connect(lambda: self._edit_node(tag))
            table = menu.addAction("Open node table")
            table.triggered.connect(lambda: self.open_tables(0))
        else:
            show.triggered.connect(lambda: self._show_element_details(tag))
            edit = menu.addAction("Edit element properties")
            edit.setEnabled(not self.model_locked)
            edit.triggered.connect(lambda: self._edit_element(tag))
            table = menu.addAction("Open element table")
            table.triggered.connect(lambda: self.open_tables(2))
        menu.addSeparator()
        delete = menu.addAction("Delete")
        delete.setEnabled(not self.model_locked)
        delete.triggered.connect(self.delete_selection)
        menu.exec(pos)

    def _show_node_details(self, tag: int) -> None:
        node = self.project.nodes.get(tag)
        if node is None:
            return
        springs = [s for s in self.project.springs.values() if s.node == tag]
        QMessageBox.information(
            self, f"Node {tag}",
            f"<b>Node {tag}</b><br>"
            f"X = {fmt(UNITS.length(node.x), 3)} {UNITS.length_unit}<br>"
            f"Y = {fmt(UNITS.length(node.y), 3)} {UNITS.length_unit}<br>"
            f"Z = {fmt(UNITS.length(node.z), 3)} {UNITS.length_unit}<br>"
            f"Restraints = {node.support_code()}<br>"
            f"Point springs = {len(springs)}")

    def _show_element_details(self, tag: int) -> None:
        element = self.project.elements.get(tag)
        if element is None:
            return
        material = self.project.material_of(element)
        section = self.project.section_of(element)
        extra = ""
        if element.kind in DEVICE_KINDS:
            device = element.device or {}
            extra = f"<br>Device = {device.get('type', element.kind)}"
        elif element.kind in ("force_beam", "disp_beam"):
            extra = (f"<br>Integration = {element.integration} "
                     f"({element.integration_points} points)")
        QMessageBox.information(
            self, f"Element {tag}",
            f"<b>Element {tag}</b><br>"
            f"Type = {element.kind}<br>"
            f"Nodes = {element.nodes}<br>"
            f"Length = {fmt(UNITS.length(self.project.element_length(element)), 3)} "
            f"{UNITS.length_unit}<br>"
            f"Material = {material.tag} {material.name}<br>"
            f"Section = {section.tag} {section.name}{extra}")

    def _edit_node(self, tag: int) -> None:
        self.viewport.select_nodes([tag])
        self.props_dock.show()
        self.props_dock.raise_()
        self.a_props_visible.blockSignals(True)
        self.a_props_visible.setChecked(True)
        self.a_props_visible.blockSignals(False)
        self.props.setCurrentIndex(1)
        self._on_selection()

    def _edit_element(self, tag: int) -> None:
        self.viewport.select_elements([tag])
        self.props_dock.show()
        self.props_dock.raise_()
        self.a_props_visible.blockSignals(True)
        self.a_props_visible.setChecked(True)
        self.a_props_visible.blockSignals(False)
        self.props.setCurrentIndex(2)
        self._on_selection()

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
                     "hinge_defs", "hinge_assignments", "springs", "constraints",
                     "ground_motions", "time_history", "response_spectrum",
                     "lanes", "vehicles", "live_load_cases",
                     "structure_groups", "boundary_groups",
                     "settings", "title"):
            setattr(p, attr, getattr(other, attr))
        p.settings["force_unit"], p.settings["length_unit"] = keep_units

    def _commit(self, label: str) -> None:
        self.project.prune_groups()
        if (self.static_results or self.modal_results or self.pushover_results
                or self.time_history_results or self.response_spectrum_results):
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
        self._cancel_draw_mode()
        self.history = History(self.project)
        self._clear_results()
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
        self._cancel_draw_mode()
        self.history = History(self.project)
        self._clear_results()
        self.viewport.set_project(self.project)
        self.refresh_all()
        self.viewport.fit()
        self._set_locked(False)

    def apply_project_dict(self, data: dict, fit: bool = True) -> None:
        """Replace the current model with a project dictionary (MCP bridge)."""
        loaded = Project.from_dict(data)
        self._adopt(loaded)
        self._cancel_draw_mode()
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
        self._refresh_mode_combo()
        self.results_scenario = res.scenario
        self.static_cache[res.scenario] = res
        self.viewport.set_load_scenario(res.scenario)
        if self.scenario_combo.findText(res.scenario) >= 0:
            self.scenario_combo.setCurrentText(res.scenario)
        self.viewport.set_static_results(res)
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        if hasattr(self, "results_panel"):
            self.results_panel.set_current_scenario(res.scenario)
        if self.viewport.show_diagrams and hasattr(self, "results_panel"):
            comps = self.results_panel.components()
            if comps:
                self.viewport.set_diagrams(
                    res, res.scenario, comps,
                    self.results_panel.diagram_scale_value(),
                    self.results_panel.diagram_show_values(),
                    self.results_panel.diagram_has_fill())
        self.viewport.fit()
        self._apply_scale()
        self.a_deformed.setChecked(True)
        self._status(f"MCP: static results for {res.scenario}")
        self._set_locked(True)
        self.ribbon.set_current("Results")

    def bridge_show_diagram(self, payload: dict) -> None:
        scenario = str(payload.get("scenario") or self.results_scenario
                       or self.scenario_combo.currentText())
        components = payload.get("components") or ["My"]
        allowed = ("Fx", "Vy", "Vz", "Mx", "My", "Mz")
        components = [str(c) for c in components if str(c) in allowed]
        if not components:
            components = ["My"]
        if hasattr(self, "results_panel"):
            self.results_panel.set_current_scenario(scenario)
            for comp, box in self.results_panel.component_boxes.items():
                box.setChecked(comp in components)
        self._apply_beam_diagram()
        self._status(f"MCP: beam diagrams for {scenario}")

    def bridge_show_mode(self, payload: dict) -> None:
        modes = [opsgen.ModeResult(int(m["mode"]), float(m["eigenvalue"]),
                                   float(m["omega"]), float(m["period"]),
                                   float(m["frequency"]))
                 for m in payload.get("modes", [])]
        shapes = {int(k): {int(n): [float(x) for x in v] for n, v in shape.items()}
                  for k, shape in (payload.get("shapes") or {}).items()}
        res = opsgen.ModalResults(modes=modes, shapes=shapes)
        self.modal_results = res
        mode = int(payload.get("mode", 1))
        self._refresh_mode_combo()
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self._clear_non_modal_overlays()
        self.viewport.set_modal_results(res, mode)
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        self.viewport.fit()
        self.viewport.start_animation()
        self.a_animate.setChecked(True)
        self._status(f"MCP: animating mode {mode}")
        self._set_locked(True)

    def bridge_show_live_load(self, payload: dict) -> None:
        from .live_load import (CaseResults, EnvelopePoint, LiveLoadConfig,
                                LiveLoadResults, Span)

        cases_raw = payload.get("cases") or {}
        cases = {}
        for key, data in cases_raw.items():
            cases[str(key)] = CaseResults(
                moment=[EnvelopePoint(float(pt[0]), float(pt[1]), float(pt[2]))
                        for pt in (data.get("moment") or [])],
                shear=[EnvelopePoint(float(pt[0]), float(pt[1]), float(pt[2]))
                       for pt in (data.get("shear") or [])],
            )
        if not cases:
            return
        load_case = str(payload.get("load_case") or next(iter(cases)))
        spans = [Span(float(s)) for s in (payload.get("spans_m") or [])]
        cfg = LiveLoadConfig(
            load_case=load_case,
            truck_model=str(payload.get("truck_model") or "CL-625"),
        )
        res = LiveLoadResults(
            load_case=load_case, cases=cases, spans=spans, axles=[],
            config=cfg, x_nodes=[], support_positions=[], truck_positions=[],
            increment_used=0.0, base_increment=0.0, increment_reason="",
            bcl_spacings=[],
        )
        for name in ("LL Max", "LL Min", "LL All"):
            if name not in self.project.cases:
                self.project.cases[name] = LoadCase(name, "Live")
        primary = "truck" if "truck" in cases else next(iter(cases))
        combined = "envelope" if "envelope" in cases else primary
        self.live_load_results = res
        self.live_load_geometry = {
            "points": [(float(p[0]), tuple(float(v) for v in p[1]))
                       for p in (payload.get("path") or [])]
        }
        self.live_load_modes = {
            "LL Max": (primary, "max"),
            "LL Min": (primary, "min"),
            "LL All": (combined, "both"),
        }
        self.refresh_all()
        self._refresh_results_panel()
        scenario = str(payload.get("scenario") or "LL All")
        if scenario not in self.live_load_modes:
            scenario = "LL All"
        allowed = ("My", "Vz", "Vy")
        components = [str(c) for c in (payload.get("components") or ["My"])
                      if str(c) in allowed]
        if not components:
            components = ["My"]
        self.results_scenario = scenario
        if self.scenario_combo.findText(scenario) >= 0:
            self.scenario_combo.setCurrentText(scenario)
        if hasattr(self, "results_panel"):
            self.results_panel.set_current_scenario(scenario)
            for comp, box in self.results_panel.component_boxes.items():
                box.setChecked(comp in components)
        self._apply_live_load_envelope(scenario)
        self.viewport.fit()
        self._status(f"MCP: live-load envelope ({scenario} · {', '.join(components)})")
        self.ribbon.set_current("Results")

    def file_new(self) -> None:
        if QMessageBox.question(self, "New project",
                                "Discard the current model and start a new project?") != QMessageBox.Yes:
            return
        self.project = default_project()
        self.project.settings = dict(self.project.settings)
        self._cancel_draw_mode()
        self.history = History(self.project)
        self._clear_results()
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
        self._cancel_draw_mode()
        self.history = History(self.project)
        self._clear_results()
        self.viewport.set_project(self.project)
        self.refresh_all()
        self.viewport.fit()
        self._set_locked(False)
        self._log(f"Opened {path}")

    def file_close(self) -> None:
        if QMessageBox.question(
                self, "Close project",
                "Close the current project and return to an Untitled model?\n"
                "Unsaved changes will be lost.") != QMessageBox.Yes:
            return
        self.project = default_project()
        self._cancel_draw_mode()
        self.history = History(self.project)
        self._clear_results()
        self.results_scenario = ""
        self.viewport.set_project(self.project)
        self.refresh_all()
        self.viewport.fit()
        self._set_locked(False)
        self._update_title()
        self._log("Project closed.")
        self._status("Project closed")

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

    def import_tcl(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Tcl", "", "Tcl files (*.tcl);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            imported, info = tcl.import_text(text, os.path.basename(path))
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        if not imported.nodes and not imported.elements:
            self._warn("No nodes or elements were found in this Tcl file.\n"
                       "Only model commands are imported; analysis commands "
                       "and procedures are skipped.")
            return
        if self.project.nodes or self.project.elements:
            answer = QMessageBox.question(
                self, "Replace model?",
                f"The current model has {len(self.project.nodes)} nodes and "
                f"{len(self.project.elements)} elements.\n\n"
                "Replace it with the Tcl model?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._cancel_draw_mode()
        self._adopt(imported)
        self.history = History(self.project)
        self._clear_results()
        self._set_locked(False)
        self.viewport.set_project(self.project)
        self.refresh_all()
        self.viewport.fit()
        message = (f"Imported {info['nodes']} nodes, {info['elements']} elements, "
                   f"{info['loads']} loads")
        if info["warnings"]:
            message += f" ({len(info['warnings'])} item(s) skipped)"
            self._log("Tcl import warnings: " + "; ".join(info["warnings"]))
        self._log(f"Tcl imported from {path}: {message}")
        self._status(message)

    def open_console(self) -> None:
        from .console import ScriptConsoleDialog

        if self.console_dialog is None:
            self.console_dialog = ScriptConsoleDialog(self.project, self)
            self.console_dialog.modelReady.connect(self.load_script_model)
        self.console_dialog.project = self.project
        self.console_dialog.show()
        self.console_dialog.raise_()
        self.console_dialog.activateWindow()

    def load_script_model(self, project, summary: str = "") -> None:
        """Adopt a model captured by a script console run."""
        if not project.nodes:
            self._warn("The script did not build any nodes.")
            return
        if self.project.nodes or self.project.elements:
            answer = QMessageBox.question(
                self, "Replace model?",
                f"The current model has {len(self.project.nodes)} nodes and "
                f"{len(self.project.elements)} elements.\n\n"
                "Replace it with the script model?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._cancel_draw_mode()
        self._adopt(project)
        self.history = History(self.project)
        self._clear_results()
        self._set_locked(False)
        self.viewport.set_project(self.project)
        self.refresh_all()
        self.viewport.fit()
        message = f"Loaded script model: {summary}" if summary else \
            "Loaded script model into Studio"
        self._status(message)
        self._log(message)

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
        self.pushover_results = None
        self.time_history_results = None
        self.response_spectrum_results = None
        if self.time_history_step_scenario:
            self.static_cache.pop(self.time_history_step_scenario, None)
            self.time_history_step_scenario = ""
        if self.time_history_dialog is not None:
            dialog = self.time_history_dialog
            self.time_history_dialog = None
            dialog.close()
        if self.response_spectrum_dialog is not None:
            dialog = self.response_spectrum_dialog
            self.response_spectrum_dialog = None
            dialog.close()
        if hasattr(self, "a_pushover_results"):
            self.a_pushover_results.setEnabled(False)
        if hasattr(self, "a_time_history_results"):
            self.a_time_history_results.setEnabled(False)
        if hasattr(self, "a_spectrum_results"):
            self.a_spectrum_results.setEnabled(False)
        self.static_cache.clear()
        self.viewport.clear_results()
        self._refresh_mode_combo()
        if hasattr(self, "results_panel"):
            for action in (self.a_beam_diagram, self.a_deformation,
                           self.a_reactions):
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)
            self.results_panel.set_note("Results cleared. Apply a diagram or "
                                        "deformation to solve the selected case.")

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
                self._warn("A two-node element needs at least 2 nodes.")
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
                        spec["vecxz"], spec["thickness"], "",
                        spec.get("behavior", ""), {},
                        spec.get("integration", "Lobatto"),
                        int(spec.get("integration_points", 5)))
            self.project.elements[tag] = e
            created.append(tag)
        self._commit(f"Created {len(created)} element(s)")
        self.viewport.select_elements(created)

    def add_device(self, preset: str) -> None:
        selected = sorted(self.viewport.sel_nodes)
        if not selected:
            self._warn("Select the two nodes of the device first, or type their "
                       "tags in the dialog.")
        dlg = DeviceDialog(self.project, selected, preset, self)
        if not dlg.exec():
            return
        spec = dlg.spec()
        tags = spec["nodes"]
        if len(tags) != 2:
            self._warn("A bearing, isolator or damper connects exactly two nodes.")
            return
        for tag in tags:
            if tag not in self.project.nodes:
                self._warn(f"Node {tag} does not exist.")
                return
        if tags[0] == tags[1]:
            self._warn("The device cannot use the same node twice.")
            return
        device = spec["device"]
        kind = spec["kind"]
        if device.get("type") == "bearing":
            if device["k_init"] <= 0 or device["kv"] <= 0:
                self._warn("The bearing needs positive shear and vertical stiffness.")
                return
        elif device.get("type") == "isolator":
            if (device["fy"] <= 0 or device["gr"] <= 0 or device["kbulk"] <= 0
                    or device["d2"] <= device["d1"] or device["tr"] <= 0):
                self._warn("The isolator needs valid strength, modulus and "
                           "diameters (D2 > D1).")
                return
        else:
            if device["k_el"] <= 0 or device["cd"] < 0:
                self._warn("The damper needs a positive elastic stiffness and a "
                           "non-negative damping coefficient.")
                return
        mat = next(iter(self.project.materials), 1)
        sec = next(iter(self.project.sections), 1)
        tag = self.project.next_element()
        self.project.elements[tag] = Element(
            tag, kind, tags, mat, sec, device=device)
        label = {"bearing": "bearing", "isolator": "isolator"}.get(
            device.get("type"), "damper")
        self._commit(f"Created {label} element {tag}")
        self.viewport.select_elements([tag])

    def toggle_draw_element(self, checked: bool) -> None:
        if checked:
            self._refresh_draw_combos()
            if not self.project.materials or not self.project.sections:
                self._warn("Create at least one material and section before "
                           "drawing elements.")
                self.a_draw_element.blockSignals(True)
                self.a_draw_element.setChecked(False)
                self.a_draw_element.blockSignals(False)
                return
            self.draw_dock.show()
            self.draw_dock.raise_()
            self.viewport.set_draw_element_mode(True)
            self._status("Draw Element: click the start node, then the end node. "
                         "Esc or Finish stops.")
            self._log("Draw Element active: click node to node. "
                      "The last node becomes the next start.")
        else:
            self.viewport.set_draw_element_mode(False)
            self.draw_dock.hide()
            self._status("Draw Element finished")

    def _cancel_draw_mode(self) -> None:
        self.a_draw_element.blockSignals(True)
        self.a_draw_element.setChecked(False)
        self.a_draw_element.blockSignals(False)
        self.viewport.set_draw_element_mode(False)
        self.draw_dock.hide()

    def _draw_element_between(self, start: int, end: int) -> None:
        if start not in self.project.nodes or end not in self.project.nodes:
            self._warn("One of the clicked nodes no longer exists.")
            return
        if start == end:
            self._warn("An element cannot reuse the same node.")
            return
        mat = int(self.draw_material.currentData() or 0)
        sec = int(self.draw_section.currentData() or 0)
        if mat not in self.project.materials:
            self._warn("Select a valid material in the Draw Element panel.")
            return
        if sec not in self.project.sections:
            self._warn("Select a valid section in the Draw Element panel.")
            return
        for element in self.project.elements.values():
            if len(element.nodes) == 2 and set(element.nodes) == {start, end}:
                self._warn(f"An element already connects nodes {start} and {end}.")
                return
        tag = self.project.next_element()
        self.project.elements[tag] = Element(
            tag, "beam", [start, end], mat, sec, None)
        self._commit(f"Created element {tag} ({start}-{end})")
        self.viewport.select_elements([tag])
        self._status(f"Draw Element: created element {tag} from node {start} "
                     f"to node {end}; continue from node {end}.")

    def run_wizard(self, kind: str) -> None:
        if not self.project.materials or not self.project.sections:
            self._warn("Create at least one material and section before "
                       "using a structure wizard.")
            return
        self._cancel_draw_mode()
        dlg = StructureWizard(self.project, kind, self)
        if not dlg.exec():
            return
        spec = dlg.spec()
        if spec["mat"] not in self.project.materials:
            self._warn("Select a valid material in the wizard.")
            return
        for key in ("col_sec", "beam_sec", "sec", "girder_sec", "cross_sec"):
            if key in spec and spec[key] not in self.project.sections:
                self._warn("Select a valid section in the wizard.")
                return
        if self.project.nodes or self.project.elements:
            answer = QMessageBox.question(
                self, "Replace model?",
                f"The current model has {len(self.project.nodes)} nodes and "
                f"{len(self.project.elements)} elements.\n\n"
                "Replace it with the wizard model? Loads and results are cleared.")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._cancel_draw_mode()
            self.project.nodes.clear()
            self.project.elements.clear()
            self.project.nodal_loads.clear()
            self.project.elem_loads.clear()
            self.project.hinge_assignments.clear()
            self.project.springs.clear()
            self.project.constraints.clear()
        self.viewport.clear_selection()
        nodes, elements = wizards.generate(self.project, spec)
        title = wizards.WIZARDS[kind][0]
        if self.project.title in ("", "Untitled"):
            self.project.title = title
        self.viewport.clear_visibility()
        self._commit(f"Generated {title}: {nodes} nodes, {elements} elements")
        self.viewport.fit()

    def subdivide(self) -> None:
        selected = sorted(self.viewport.sel_elements)
        eligible = []
        for t in selected:
            e = self.project.elements.get(t)
            if (e is not None and e.kind in ("beam", "truss", "force_beam", "disp_beam")
                    and len(e.nodes) == 2
                    and self.project.element_length(e) > 1e-9):
                eligible.append(t)
        if not eligible:
            if selected:
                self._warn("Subdivision applies to beam, nonlinear frame and "
                           "truss elements with two nodes.")
            else:
                self._warn("Select the beam, frame or truss elements to subdivide.")
            return
        dlg = dialogs.SubdivideDialog(len(eligible), len(selected), self)
        if not dlg.exec():
            return
        divisions = dlg.spec()
        new_nodes, new_elems = self.project.subdivide_elements(eligible, divisions)
        self._commit(f"Subdivided {len(eligible)} element(s) into {divisions} parts")
        self.viewport.select_elements(new_elems)
        self._status(f"Created {len(new_elems)} element(s) and "
                     f"{len(new_nodes)} node(s)")

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
                    list(e.vecxz) if e.vecxz else None, e.thickness, e.group,
                    e.behavior, dict(e.device), e.integration,
                    e.integration_points)
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
        dlg.previewChanged.connect(self.viewport.set_mirror_plane)
        dlg.refresh_preview()
        accepted = dlg.exec()
        self.viewport.clear_mirror_plane()
        if not accepted:
            return
        axis, offset, copy, with_elements = dlg.spec()
        elem_set = set(self.viewport.sel_elements)
        if with_elements:
            for t, e in self.project.elements.items():
                if all(n in node_set for n in e.nodes):
                    elem_set.add(t)

        def flip(xyz):
            c = list(xyz)
            c[axis] = 2.0 * offset - c[axis]
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
                    tag, e.kind, nodes, e.mat, e.sec,
                    list(e.vecxz) if e.vecxz else None, e.thickness, e.group,
                    e.behavior, dict(e.device), e.integration,
                    e.integration_points)
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

    def add_point_springs(self) -> None:
        if self.model_locked:
            self._warn("The model is locked. Press Ctrl+L to unlock before editing.")
            return
        if not self.project.nodes:
            self._warn("Create nodes first.")
            return
        dlg = boundary_dialogs.SpringDialog(
            self.project, sorted(self.viewport.sel_nodes), self)
        if not dlg.exec():
            return
        targets = dlg.targets()
        if not targets:
            self._warn("Specify at least one valid node for the spring.")
            return
        spec = dlg.spec()
        if spec["kind"] == "py" and int(spec["dof"]) > 3:
            self._warn("PySimple1 springs apply to translational DOFs only.")
            return
        if spec["kind"] == "multilinear" and len(spec["curve"]) < 2:
            self._warn("Enter at least two force-deformation points.")
            return
        if spec["behavior"] == "compression" and spec["kind"] == "multilinear":
            self._warn("OpenSees has no compression-only wrapper for a "
                       "multi-linear curve. Use linear compression-only or ENT.")
            return
        for node in targets:
            for tag, spring in list(self.project.springs.items()):
                if spring.node == node and spring.dof == spec["dof"]:
                    del self.project.springs[tag]
            tag = self.project.next_spring()
            self.project.springs[tag] = SpringSupport(tag, node, **spec)
        self._commit(
            f"Created {len(targets)} point spring(s) on DOF {spec['dof']}")

    def _add_constraint(self, dlg) -> None:
        if self.model_locked:
            self._warn("The model is locked. Press Ctrl+L to unlock before editing.")
            return
        spec = dlg.spec()
        if not spec["slaves"]:
            self._warn("Specify at least one valid slave node.")
            return
        if spec["kind"] == "equal_dof" and not spec["dofs"]:
            self._warn("Select at least one DOF to tie.")
            return
        tag = self.project.next_constraint()
        self.project.constraints[tag] = BoundaryConstraint(tag, **spec)
        label = {
            "rigid_beam": "rigid beam link",
            "rigid_bar": "rigid bar link",
            "equal_dof": "equalDOF constraint",
            "rigid_diaphragm": "rigid diaphragm",
        }.get(spec["kind"], spec["kind"])
        self._commit(f"Created {label} {tag}")

    def add_rigid_link(self) -> None:
        if not self.project.nodes:
            self._warn("Create nodes first.")
            return
        dlg = boundary_dialogs.RigidLinkDialog(
            self.project, sorted(self.viewport.sel_nodes), self)
        if dlg.exec():
            self._add_constraint(dlg)

    def add_equal_dof(self) -> None:
        if not self.project.nodes:
            self._warn("Create nodes first.")
            return
        dlg = boundary_dialogs.EqualDOFDialog(
            self.project, sorted(self.viewport.sel_nodes), self)
        if dlg.exec():
            self._add_constraint(dlg)

    def add_diaphragm(self) -> None:
        if not self.project.nodes:
            self._warn("Create nodes first.")
            return
        dlg = boundary_dialogs.DiaphragmDialog(
            self.project, sorted(self.viewport.sel_nodes), self)
        if dlg.exec():
            self._add_constraint(dlg)

    def _delete_boundary(self, kind: str, tag: int) -> None:
        if self.model_locked:
            self._warn("The model is locked. Press Ctrl+L to unlock before editing.")
            return
        if kind == "spring":
            self.project.springs.pop(int(tag), None)
            self._commit(f"Deleted point spring {tag}")
        else:
            self.project.constraints.pop(int(tag), None)
            self._commit(f"Deleted constraint {tag}")

    def materials(self, add_new: bool = False) -> None:
        dlg = dialogs.MaterialDialog(self.project, self)
        if add_new:
            dlg._add()
        if not dlg.exec():
            return
        missing = [e.tag for e in self.project.elements.values()
                   if e.mat not in dlg.materials]
        if missing:
            self._warn(f"Elements {missing[:8]} reference deleted materials.")
            return
        self.project.materials = dlg.materials
        self._commit("Edited materials")

    def section_properties(self) -> None:
        from .tools_dialogs import SectionPropertyDialog

        dlg = SectionPropertyDialog(self.project, self)
        if not dlg.exec():
            return
        section = dlg.result_section()
        if section is None:
            return
        self.project.sections[section.tag] = section
        self._commit(f"Added custom section {section.name}")
        self.refresh_all()
        self._log(f"Section Property Pro: {section.name} - "
                  f"A={fmt(UNITS.area(section.A), 2)} {UNITS.area_unit}, "
                  f"Iy={fmt(UNITS.inertia(section.Iy), 2)} {UNITS.inertia_unit}, "
                  f"Iz={fmt(UNITS.inertia(section.Iz), 2)} {UNITS.inertia_unit}, "
                  f"J={fmt(UNITS.inertia(section.J), 2)} {UNITS.inertia_unit}.")
        library = dialogs.SectionDialog(self.project, self,
                                        select_tag=section.tag)
        if library.exec():
            self.project.sections = library.sections
            self._commit("Edited section library")
            self.refresh_all()

    def moment_curvature(self) -> None:
        from .tools_dialogs import MomentCurvatureDialog

        selected = [t for t in self.viewport.sel_elements
                    if t in self.project.elements
                    and self.project.elements[t].kind == "beam"]
        dlg = MomentCurvatureDialog(self.project, selected, self)
        if not dlg.exec():
            return
        hinge = dlg.hinge()
        if hinge is None:
            return
        self.project.hinge_defs[hinge.tag] = hinge
        assigned = 0
        if dlg.assign.isChecked():
            for tag in selected:
                self.project.hinge_assignments[tag] = hinge.tag
                assigned += 1
        points = ", ".join(f"{r:.4g} rad / {m / 1000.0:.4g} {UNITS.moment_unit}"
                           for r, m in hinge.curve)
        self._commit(f"Created moment backbone hinge {hinge.name}")
        self.refresh_all()
        self._log(f"Moment Curvature Pro: {hinge.name} "
                  f"(H{hinge.tag}, {hinge.material}); backbone "
                  f"{points}; {assigned} beam element(s) assigned.")
        self._status(f"Moment backbone H{hinge.tag} created"
                     + (f" and assigned to {assigned} element(s)" if assigned else ""))

    def vehicle_definitions(self) -> None:
        from .vehicle_dialog import VehicleDialog

        dlg = VehicleDialog(self.project, self)
        if not dlg.exec():
            return
        self.project.vehicles = dict(dlg.vehicles)
        self._commit("Edited moving vehicles")
        self._log(f"Moving vehicles: {len(self.project.vehicles)} defined.")
        self._status("Vehicle definitions updated")

    def lane_definitions(self) -> None:
        from .lane_dialog import LaneDialog

        node_tags = set(self.viewport.sel_nodes)
        for tag in self.viewport.sel_elements:
            e = self.project.elements.get(tag)
            if e is not None:
                node_tags.update(e.nodes)
        selected = sorted(
            (tag for tag in node_tags if tag in self.project.nodes),
            key=lambda tag: self.project.nodes[tag].xyz)
        dlg = LaneDialog(self.project, selected,
                         sorted(self.viewport.sel_elements), self)
        if not dlg.exec():
            return
        self.project.lanes = {
            tag: lane for tag, lane in dlg.lanes.items() if lane.length > 1e-6}
        self._commit("Edited traffic lanes")
        self.viewport.update()
        self._log(f"Traffic lanes: {len(self.project.lanes)} defined.")
        self._status("Traffic lane definitions updated")

    def live_load(self) -> None:
        from .live_load_case_dialog import LiveLoadCaseDialog

        selected = [t for t in self.viewport.sel_elements
                    if t in self.project.elements]
        dlg = LiveLoadCaseDialog(self.project, selected, self)
        if not dlg.exec():
            return
        if dlg.results is None:
            return
        result = dlg.results
        for name in ("LL Max", "LL Min", "LL All"):
            if name not in self.project.cases:
                self.project.cases[name] = LoadCase(name, "Live")
        vehicle_tag = dlg.vehicle_combo.currentData()
        lane_tag = dlg.lane_combo.currentData()
        case_name = dlg.case_name.text().strip() or "LL"
        self.project.live_load_cases[case_name] = LiveLoadCase(
            case_name,
            int(vehicle_tag) if vehicle_tag is not None else 0,
            int(lane_tag) if lane_tag is not None else 0,
            dlg.lane_udl.value(),
            (dlg.dla_override.value() / 100.0
             if dlg.dla_mode.currentData() == "manual" else None),
            dlg.dla_multiplier.value() / 100.0)
        self.project.settings["live_load"] = result.config.__dict__
        self.live_load_results = result
        self.live_load_geometry = dlg.chain_geometry
        self.live_load_modes = {
            "LL Max": ("truck", "max"),
            "LL Min": ("truck", "min"),
            "LL All": ("envelope", "both"),
        }
        self._commit("Live load analysis")
        self._refresh_results_panel()
        self.results_scenario = "LL All"
        self.scenario_combo.setCurrentText("LL All")
        if hasattr(self, "results_panel"):
            self.results_panel.set_current_scenario("LL All")
            self.results_panel.component_boxes["My"].setChecked(True)
            self.results_panel.component_boxes["Vz"].setChecked(True)
            self.results_panel.component_boxes["Mz"].setChecked(False)
        self.results_dock.show()
        self.results_dock.raise_()
        self._apply_beam_diagram()
        env = result.cases["envelope"].moment
        truck = result.cases["truck"].moment
        self._log(
            f"Live load: {result.load_case}, spans "
            f"{', '.join(f'{s.length:g}' for s in result.spans)} m, "
            f"{len(result.axles)} axles, {result.increment_used:g} m sweep; "
            f"LL Max {max(p.max for p in truck):.3f} kN m, "
            f"LL Min {min(p.min for p in truck):.3f} kN m, "
            f"LL All {max(p.max for p in env):.3f} / "
            f"{min(p.min for p in env):.3f} kN m.")
        self._status("Live-load envelopes applied to the model")

    def sections(self, add_new: bool = False) -> None:
        dlg = dialogs.SectionDialog(self.project, self)
        if add_new:
            dlg.start_new()
        if not dlg.exec():
            return
        missing = [e.tag for e in self.project.elements.values()
                   if e.sec not in dlg.sections]
        if missing:
            self._warn(f"Elements {missing[:8]} reference deleted sections.")
            return
        self.project.sections = dlg.sections
        self._commit("Edited sections")

    def edit_hinge_defs(self, add_new: bool = False) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        dlg = HingeLibraryDialog(self.project, self)
        if add_new:
            dlg._new()
        if not dlg.exec():
            return
        self.project.hinge_defs = dlg.defs
        self.project.hinge_assignments = {
            e: h for e, h in self.project.hinge_assignments.items()
            if h in self.project.hinge_defs}
        self._commit(f"Edited hinge library ({len(dlg.defs)} definition(s))")

    def assign_hinges(self) -> None:
        if self.model_locked:
            self._status("Model is locked - press Ctrl+L to unlock before editing.")
            return
        if not self.project.hinge_defs:
            self._warn("Create at least one hinge definition first (Define Hinges).")
            return
        dlg = AssignHingesDialog(self.project, self,
                                 selected=sorted(self.viewport.sel_elements))
        if not dlg.exec():
            return
        self.project.hinge_assignments = dlg.assignments
        self._commit(f"Assigned hinges to {len(dlg.assignments)} element(s)")

    # =================================================================== loads
    def load_cases(self, add_new: bool = False) -> None:
        dlg = dialogs.LoadCaseDialog(self.project, self)
        if add_new:
            dlg._add()
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

    def combinations(self, add_new: bool = False) -> None:
        dlg = dialogs.ComboDialog(self.project, self)
        if add_new:
            dlg._add()
        if not dlg.exec():
            return
        self.project.combos = dlg.combos
        self._commit("Edited load combinations")

    # ================================================================ analysis
    def analysis_settings(self) -> None:
        dlg = dialogs.AnalysisDialog(self.project, self)
        if not dlg.exec():
            return
        self._save_analysis_settings(dlg)

    def modal_settings(self) -> None:
        dlg = dialogs.AnalysisDialog(self.project, self)
        dlg.show_tab("modal")
        if not dlg.exec():
            return
        self._save_analysis_settings(dlg)

    def _save_analysis_settings(self, dlg) -> None:
        values = dlg.values()
        modal_changed = (
            int(values.get("modal_modes", 6))
            != int(self.project.settings.get("modal_modes", 6))
            or bool(values.get("mass_from_density", True))
            != bool(self.project.settings.get("mass_from_density", True))
            or str(values.get("eigen_solver", "fullGenLapack"))
            != str(self.project.settings.get("eigen_solver", "fullGenLapack")))
        self.project.settings.update(values)
        if modal_changed:
            self.project.settings["modal_configured"] = True
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

    def _run_analysis(self, kind: str, config: dict, title: str, on_finished) -> None:
        if self.analysis_runner is not None and self.analysis_runner.is_running:
            self._warn("An analysis is already running.")
            return
        runner = AnalysisRunner(self)
        self.analysis_runner = runner
        dialog = AnalysisProgressDialog(title, runner, self)
        runner.failed.connect(
            lambda msg: self._log(f"✖ {title} failed: {msg.splitlines()[0]}"))
        runner.cancelled.connect(lambda: self._status(f"{title} cancelled"))
        self._status(f"Running {title.lower()}…")
        try:
            runner.run(self.project, kind, config)
        except Exception as exc:
            self.analysis_runner = None
            QMessageBox.critical(self, title, str(exc))
            self._log(f"✖ {title} failed: {exc}")
            return
        if runner.completed:
            if runner.result is not None:
                on_finished(runner.result)
            self.analysis_runner = None
            return
        dialog.exec()
        if runner.result is not None:
            on_finished(runner.result)
        self.analysis_runner = None

    def run_analysis_control(self) -> None:
        if self.analysis_runner is not None and self.analysis_runner.is_running:
            self._warn("An analysis is already running.")
            return
        if not self.project.elements:
            self._warn("The model has no elements.")
            return
        dlg = runcontrol.RunControlDialog(
            self.project, self.scenario_combo.currentText(), self)
        if not dlg.exec():
            return
        selected = dlg.selected()
        if not selected:
            self._warn("Select at least one available analysis.")
            return
        jobs = []
        if "static" in selected:
            jobs.append(("static", {"scenario": dlg.static_scenario},
                         "Static analysis", self._static_finished))
        if "modal" in selected:
            modes = int(self.project.settings.get("modal_modes", 6))
            jobs.append(("modal", {"nmodes": modes}, "Modal analysis",
                         self._modal_finished))
        if "pushover" in selected:
            jobs.append(("pushover", dlg.pushover_config(),
                         "Pushover analysis", self._pushover_finished))
        if "time_history" in selected:
            jobs.append(("time_history", {}, "Time-history analysis",
                         self._time_history_finished))
        if "response_spectrum" in selected:
            jobs.append(("response_spectrum", {},
                         "Response-spectrum analysis",
                         self._response_spectrum_finished))
        self._log("Run control: " + ", ".join(selected))
        for kind, config, title, callback in jobs:
            if self.analysis_runner is not None and self.analysis_runner.is_running:
                break
            self._run_analysis(kind, config, title, callback)
        self._status(f"Analysis run control finished ({len(jobs)} job(s))")

    def run_static(self) -> None:
        scenario = self._scenario()
        if not scenario:
            return
        if not self.project.elements:
            self._warn("The model has no elements.")
            return
        self._run_analysis("static", {"scenario": scenario},
                           "Static analysis", self._static_finished)

    def _static_finished(self, res: opsgen.StaticResults) -> None:
        self.static_results = res
        scenario = res.scenario
        self.results_scenario = scenario
        self.static_cache[scenario] = res
        self.viewport.set_load_scenario(scenario)
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        self.viewport.set_static_results(res)
        self._apply_scale()
        self._refresh_mode_combo()
        self._log(f"Static analysis '{scenario}' complete. Max |u| = "
                  f"{fmt(UNITS.length(res.max_disp), 4)} {UNITS.length_unit}")
        self._status(f"Static analysis complete - max displacement "
                     f"{fmt(UNITS.length(res.max_disp), 4)} {UNITS.length_unit}")
        self.a_animate.setChecked(False)
        self._set_locked(True)
        self.ribbon.set_current("Results")
        if hasattr(self, "results_panel"):
            self.results_panel.set_current_scenario(scenario)
        if self.viewport.show_diagrams:
            self._apply_beam_diagram()
        if self.a_reactions.isChecked():
            self._apply_reactions()
        self._log("Model locked after analysis. Press Ctrl+L to unlock before editing.")

    def run_modal(self) -> None:
        if not self.project.elements:
            self._warn("The model has no elements.")
            return
        nmodes = int(self.project.settings.get("modal_modes", 6))
        self._run_analysis("modal", {"nmodes": nmodes},
                           "Modal analysis", self._modal_finished)

    def _modal_finished(self, res: opsgen.ModalResults) -> None:
        self.modal_results = res
        self._refresh_mode_combo()
        if self.mode_combo.count():
            self.mode_combo.setCurrentIndex(0)
            self._mode_selected(0)
        else:
            self._clear_non_modal_overlays()
            self.viewport.set_modal_results(res, 1)
        txt = ", ".join(f"T{m.mode}={fmt(m.period, 4)}s" for m in res.modes[:4])
        self._log(f"Modal analysis complete: {txt}")
        self._status(f"Modal analysis complete - {len(res.modes)} modes")
        self._set_locked(True)
        self.ribbon.set_current("Results")
        self._log("Model locked after analysis. Press Ctrl+L to unlock before editing.")

    def pushover(self) -> None:
        if not self.project.elements:
            self._warn("The model has no elements.")
            return
        selected = next(iter(self.viewport.sel_nodes), None)
        dlg = dialogs.PushoverDialog(self.project, selected, self)
        if not dlg.exec():
            return
        cfg = dlg.spec()
        if not cfg.get("lateral_case"):
            self._warn("Select a lateral load case or combination.")
            return
        assigned = [e for e, h in self.project.hinge_assignments.items()
                    if h in self.project.hinge_defs
                    and HINGE_MATERIALS.get(self.project.hinge_defs[h].material) is not None
                    and (HINGE_MATERIALS[self.project.hinge_defs[h].material].kind == "fiber"
                         or (HINGE_MATERIALS[self.project.hinge_defs[h].material].kind == "spring"
                             and self.project.hinge_defs[h].material in SPRING_HINGE_MATERIALS
                             and self.project.hinge_defs[h].curve))
                    and e in self.project.elements
                    and self.project.elements[e].kind == "beam"]
        if not assigned:
            self._warn("Create hinge definitions and assign them to beam "
                       "elements before running pushover.")
            return
        settings = dict(self.project.settings.get("pushover", {}))
        settings.update(cfg)
        self.project.settings["pushover"] = settings
        self.project.settings["pushover_configured"] = True
        used_defs = {self.project.hinge_assignments[e] for e in assigned}
        models = ", ".join(sorted({
            self.project.hinge_defs[t].material for t in used_defs
            if t in self.project.hinge_defs}))
        self._log(f"Pushover: {len(assigned)} hinge element(s) "
                  f"[{models}], gravity '{cfg['gravity_case'] or 'none'}', "
                  f"lateral '{cfg['lateral_case']}', target "
                  f"{fmt(UNITS.length(cfg['target_displacement']), 3)} "
                  f"{UNITS.length_unit}.")
        self._run_analysis("pushover", cfg, "Pushover analysis",
                           self._pushover_finished)

    def _pushover_finished(self, res: opsgen.PushoverResults) -> None:
        self._clear_results()
        self.pushover_results = res
        self.a_pushover_results.setEnabled(True)
        self._set_locked(True)
        self.ribbon.set_current("Pushover")
        last = max(0, len(res.steps) - 1)
        self._show_pushover_step(last)
        self._log(f"✔ Pushover complete: {len(res.steps) - 1} steps, "
                  f"max base shear "
                  f"{fmt(UNITS.force(max((s.base_shear for s in res.steps), default=0.0)), 3)} "
                  f"{UNITS.force_unit}.")
        self._status(f"Pushover complete - {len(res.steps) - 1} steps")
        self.show_pushover_results()

    def show_pushover_results(self) -> None:
        if self.pushover_results is None:
            self._warn("Run a pushover analysis first.")
            return
        dlg = PushoverResultsDialog(self.project, self.pushover_results, self)
        dlg.stepSelected.connect(self._show_pushover_step)
        dlg.exec()

    def _show_pushover_step(self, index: int) -> None:
        if self.pushover_results is None:
            return
        if not (0 <= index < len(self.pushover_results.steps)):
            return
        step = self.pushover_results.steps[index]
        self.viewport.set_static_results(self.pushover_results.static_at(index))
        self.viewport.set_load_scenario(self.pushover_results.lateral_case)
        self.viewport.show_deformed = True
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        self.a_deformed.blockSignals(True)
        self.a_deformed.setChecked(True)
        self.a_deformed.blockSignals(False)
        self._apply_scale()
        self.viewport.update()
        self._status(f"Pushover step {step.step}: "
                     f"u = {fmt(UNITS.length(step.displacement), 3)} "
                     f"{UNITS.length_unit}, "
                     f"V = {fmt(UNITS.force(step.base_shear), 3)} "
                     f"{UNITS.force_unit}")

    def define_time_history(self) -> None:
        dlg = dialogs.TimeHistoryDialog(self.project, self)
        if not dlg.exec():
            return
        self.project.time_history = dlg.spec()
        self.project.settings["th_configured"] = True
        self._commit("Edited time-history case")
        case = self.project.time_history
        source = "sine" if case.source == "sine" else case.path
        self._log(f"Time-history case '{case.name}' saved ({source}).")
        self._status("Time-history case saved")

    def run_time_history(self) -> None:
        if not self.project.elements:
            self._warn("The model has no elements.")
            return
        case = self.project.time_history
        if case.source == "file" and not case.path:
            self.define_time_history()
            case = self.project.time_history
            if case.source == "file" and not case.path:
                return
        self._run_analysis("time_history", {}, "Time-history analysis",
                           self._time_history_finished)

    def _time_history_finished(self, res: opsgen.TimeHistoryResults) -> None:
        self._clear_results()
        self.time_history_results = res
        self.a_time_history_results.setEnabled(True)
        self._set_locked(True)
        self.ribbon.set_current("Results")
        suffix = " (stopped early)" if res.early_stop else ""
        self._log(
            f"✔ Time history '{res.case_name}' complete: {res.n_steps} of "
            f"{res.n_steps_requested} steps; peak |u| = "
            f"{fmt(UNITS.length(res.peak_disp), 4)} {UNITS.length_unit}.{suffix}")
        self._status(f"Time-history complete - {res.n_steps} steps")
        self.show_time_history_results()

    def show_time_history_results(self) -> None:
        if self.time_history_results is None:
            self._warn("Run a time-history analysis first.")
            return
        if self.time_history_dialog is not None:
            self.time_history_dialog.close()
            self.time_history_dialog = None
        dlg = TimeHistoryResultsDialog(self.project, self.time_history_results,
                                       self)
        dlg.stepSelected.connect(self._show_time_history_step)
        dlg.destroyed.connect(self._time_history_dialog_closed)
        self.time_history_dialog = dlg
        dlg.show()
        dlg.raise_()
        self._show_time_history_step(dlg.current_step)

    def _time_history_dialog_closed(self, *_args) -> None:
        self.time_history_dialog = None
        if hasattr(self, "results_panel"):
            self._refresh_results_panel()

    def _show_time_history_step(self, index: int) -> None:
        results = self.time_history_results
        if results is None or not results.time:
            return
        index = max(0, min(int(index), len(results.time) - 1))
        displacements = {
            nid: list(rows[index])
            for nid, rows in results.node_disp.items()
            if 0 <= index < len(rows)
        }
        element_forces = {
            eid: list(rows[index])
            for eid, rows in results.element_forces.items()
            if 0 <= index < len(rows)
        }
        element_kind = {
            eid: self.project.elements[eid].kind
            for eid in element_forces if eid in self.project.elements
        }
        max_disp = max(
            (max(abs(v) for v in row) for row in displacements.values()),
            default=0.0)
        scenario = f"{results.case_name} step {index + 1}"
        if (self.time_history_step_scenario
                and self.time_history_step_scenario != scenario):
            self.static_cache.pop(self.time_history_step_scenario, None)
        self.time_history_step_scenario = scenario
        res = opsgen.StaticResults(
            scenario=scenario,
            displacements=displacements,
            element_forces=element_forces,
            element_kind=element_kind,
            max_disp=max_disp,
            log=results.log)
        self.static_cache[scenario] = res
        if hasattr(self, "results_panel"):
            self.results_panel.set_scenarios([scenario])
            self.results_panel.set_current_scenario(scenario)
        self.viewport.set_load_scenario(scenario)
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        self.viewport.set_static_results(res)
        self.viewport.show_deformed = True
        self.a_deformed.blockSignals(True)
        self.a_deformed.setChecked(True)
        self.a_deformed.blockSignals(False)
        self._apply_scale()
        if self.viewport.show_diagrams and hasattr(self, "results_panel"):
            comps = self.results_panel.components()
            if comps:
                self.viewport.set_diagrams(
                    res, scenario, comps,
                    self.results_panel.diagram_scale_value(),
                    self.results_panel.diagram_show_values(),
                    self.results_panel.diagram_has_fill())
        self.viewport.update()
        self._status(
            f"Time history step {index + 1}/{len(results.time)}: "
            f"t = {results.time[index]:.4g} s, "
            f"max |u| = {fmt(UNITS.length(max_disp), 4)} "
            f"{UNITS.length_unit}")

    def ground_motion_catalog(self) -> None:
        dlg = GroundMotionCatalogDialog(self.project, self)
        if not dlg.exec():
            return
        self.project.ground_motions = dlg.records
        self._commit("Edited ground-motion catalog")
        self._log(f"Ground-motion catalog: "
                  f"{len(self.project.ground_motions)} record(s).")

    def define_response_spectrum(self) -> None:
        dlg = ResponseSpectrumDialog(self.project, self)
        if not dlg.exec():
            return
        self.project.response_spectrum = dlg.spec()
        self.project.settings["rs_configured"] = True
        self._commit("Edited response-spectrum case")
        case = self.project.response_spectrum
        self._log(f"Response-spectrum case '{case.name}' saved: "
                  f"{len(case.periods)} points, {case.combination}.")

    def run_response_spectrum(self) -> None:
        if not self.project.elements:
            self._warn("The model has no elements.")
            return
        self._run_analysis("response_spectrum", {},
                           "Response-spectrum analysis",
                           self._response_spectrum_finished)

    def _response_spectrum_finished(self,
                                    res: opsgen.ResponseSpectrumResults) -> None:
        self._clear_results()
        self.response_spectrum_results = res
        self.a_spectrum_results.setEnabled(True)
        self._set_locked(True)
        self.ribbon.set_current("Results")
        self._show_response_spectrum_model()
        self._log(
            f"✔ Response spectrum '{res.case_name}' complete: {res.n_modes} "
            f"modes, peak |u| = {fmt(UNITS.length(res.peak_disp), 4)} "
            f"{UNITS.length_unit}.")
        self._status(f"Response spectrum complete - {res.n_modes} modes")
        self.show_response_spectrum_results()

    def _show_response_spectrum_model(self) -> None:
        results = self.response_spectrum_results
        if results is None:
            return
        static = results.static_at()
        self.static_cache[static.scenario] = static
        if hasattr(self, "results_panel"):
            self.results_panel.set_scenarios([static.scenario])
            self.results_panel.set_current_scenario(static.scenario)
        self.viewport.set_load_scenario(static.scenario)
        self.viewport.show_loads = False
        self.a_loads_visible.blockSignals(True)
        self.a_loads_visible.setChecked(False)
        self.a_loads_visible.blockSignals(False)
        self.viewport.set_static_results(static)
        self.viewport.show_deformed = True
        self.a_deformed.blockSignals(True)
        self.a_deformed.setChecked(True)
        self.a_deformed.blockSignals(False)
        self._apply_scale()
        if self.viewport.show_diagrams and hasattr(self, "results_panel"):
            comps = self.results_panel.components()
            if comps:
                self.viewport.set_diagrams(
                    static, static.scenario, comps,
                    self.results_panel.diagram_scale_value(),
                    self.results_panel.diagram_show_values(),
                    self.results_panel.diagram_has_fill())
        self.viewport.update()

    def show_response_spectrum_results(self) -> None:
        if self.response_spectrum_results is None:
            self._warn("Run a response-spectrum analysis first.")
            return
        if self.response_spectrum_dialog is not None:
            self.response_spectrum_dialog.close()
            self.response_spectrum_dialog = None
        dlg = ResponseSpectrumResultsDialog(
            self.project, self.response_spectrum_results, self)
        dlg.showDeformed.connect(self._show_response_spectrum_model)
        dlg.destroyed.connect(self._response_spectrum_dialog_closed)
        self.response_spectrum_dialog = dlg
        dlg.show()
        dlg.raise_()
        self._show_response_spectrum_model()

    def _response_spectrum_dialog_closed(self, *_args) -> None:
        self.response_spectrum_dialog = None
        if hasattr(self, "results_panel"):
            self._refresh_results_panel()

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
        self.viewport.set_load_scenario(scenario)
        self.viewport.set_static_results(self.static_results)
        self._apply_scale()
        self.viewport.show_deformed = True
        self.viewport.show_deformation_values = (
            self.results_panel.deformation_show_values())
        self.a_deformed.setChecked(True)
        self.viewport.fit()

    def _plot_mode(self, mode: int) -> None:
        if not self.modal_results:
            return
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self._mode_selected(max(0, index))
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
        self.project.hinge_assignments = {
            t: h for t, h in self.project.hinge_assignments.items()
            if t in self.project.elements and h in self.project.hinge_defs}
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
    def open_tables_for_current_tab(self) -> None:
        """Open the table most relevant to the active ribbon tab."""
        title = self.ribbon.current_title() if hasattr(self, "ribbon") else ""
        tab = {
            "Node/Element": 2,
            "Properties": 4,
            "Boundary": 1,
            "Load": 7,
        }.get(title, 0)
        self.open_tables(tab)

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
            "<li><b>Batch Element (E)</b> — select nodes first, then pick beam / truss / shell.</li>"
            "<li><b>Draw Element</b> — choose material/section in the side panel, then click node to node.</li>"
            "<li><b>Copy / Move (C)</b> and <b>Mirror (M)</b> — replicate storeys or spans.</li>"
            "<li><b>Supports (S)</b> — fixed, pinned or roller restraints.</li>"
            "<li><b>Load Cases</b>, <b>Nodal Loads (L)</b>, <b>Element Loads</b>, <b>Self Weight</b>.</li>"
            "<li><b>Combinations (K)</b> — factor each case.</li>"
            "<li><b>Run Analysis (F5)</b> — choose static, modal, pushover, time history "
            "or response spectrum; <b>Modal (F6)</b>, then results (F7).</li>"
            "</ol>"
            "<p>The active load case is chosen in the status bar; loads are drawn for it.</p>"
            "<p><b>Mouse:</b> left = select / box-select, middle = pan, right = orbit, wheel = zoom.<br>"
            "<b>Tables (T)</b> edits every entity in a spreadsheet.</p>"))

    def show_faq(self) -> None:
        FaqDialog(self).exec()

    def open_opensees_help(self) -> None:
        QDesktopServices.openUrl(
            QUrl("https://opensees.berkeley.edu/wiki/index.php/Main_Page"))

    def _show_update(self, version: str, url: str) -> None:
        self.update_version = version
        self.update_url = url
        self.update_button.setText(f"Update {version}")
        self.update_button.setToolTip(
            f"OpenSees Studio {version} is available - click to download the installer")
        self.update_button.show()

    def _open_update(self) -> None:
        if self.update_url:
            QDesktopServices.openUrl(QUrl(self.update_url))

    def about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}", self.about_text())

    def about_text(self) -> str:
        return (
            f"<h3>{APP_NAME}</h3>"
            f"<p><b>Version {APP_VERSION}</b></p>"
            "<p>Graphical model generation for OpenSees.</p>"
            "<p>Display units: " + UNITS.label() + ".<br>"
            "Model data is stored in kN, mm, tonne, s.<br>"
            "Engine: OpenSeesPy 3.8.0<br>"
            "Interface: PySide6 / Qt 6</p>"
            "<p>License: PolyForm Noncommercial 1.0.0 "
            "(source-available; noncommercial use only).<br>"
            "OpenSees/OpenSeesPy and Qt third-party notices are installed "
            "with the application.</p>"
            "<p><b>Early alpha — research and education use only.</b> Under "
            "active development; results are not fully verified. Test and "
            "verify before use. Not intended for real-world commercial work, "
            "design decisions, or any application involving public safety. "
            "Use at your own risk.</p>"
            "<p>Features: nodes, elastic and fibre beam-column elements, "
            "trusses, cables, shells, bearings, isolators, dampers, "
            "copy-move-mirror, supports, load cases, nodal and element loads, "
            "self weight, load combinations, static and modal analysis, "
            "pushover, time history, response spectrum, Tcl export and "
            "spreadsheet tables.</p>")

    # ================================================================ shutdown
    def closeEvent(self, event) -> None:
        event.accept()
