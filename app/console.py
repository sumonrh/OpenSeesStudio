"""Script console: write and run OpenSeesPy Python or OpenSees Tcl."""

from __future__ import annotations

import traceback

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout)

from . import opsgen, scriptmodel, theme, tcl

PYTHON_SAMPLE = """# Units: m, kN, kN/m2 (set in the Units list).
# Model commands are captured and can be loaded into Studio.
ops.wipe()
ops.model("BasicBuilder", "-ndm", 2, "-ndf", 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 0.0, 3.0)
ops.node(3, 4.0, 3.0)
ops.fix(1, 1, 1, 1)
ops.geomTransf("Linear", 1)
ops.uniaxialMaterial("Elastic", 1, 34e6)
ops.element("elasticBeamColumn", 1, 1, 2, 0.25, 34e6, 0.0052, 1)
ops.element("elasticBeamColumn", 2, 2, 3, 0.25, 34e6, 0.0052, 1)
print("Frame built:", ops.getNodeTags(), ops.getEleTags())
"""

TCL_SAMPLE = """# OpenSees Tcl console (units: m, kN, kN/m2).
wipe
model BasicBuilder -ndm 2 -ndf 3
node 1 0.0 0.0
node 2 0.0 3.0
node 3 4.0 3.0
fix 1 1 1 1
geomTransf Linear 1
uniaxialMaterial Elastic 1 34e6
element elasticBeamColumn 1 1 2 0.25 34e6 0.0052 1
element elasticBeamColumn 2 2 3 0.25 34e6 0.0052 1
puts "Tcl frame built"
"""


class ScriptConsoleDialog(QDialog):
    """One window for Python (OpenSeesPy) and Tcl scripts."""

    modelReady = Signal(object, str)

    def __init__(self, project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Script Console")
        self.resize(980, 680)
        self.project = project
        self._texts = {"python": PYTHON_SAMPLE, "tcl": TCL_SAMPLE}
        self._last_project = None
        self._last_summary = ""

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Language"))
        self.language = QComboBox()
        self.language.addItem("Python (OpenSeesPy)", "python")
        self.language.addItem("Tcl (OpenSees commands)", "tcl")
        row.addWidget(self.language)
        row.addWidget(QLabel("Units"))
        self.units = QComboBox()
        for key, label in scriptmodel.UNIT_LABELS.items():
            self.units.addItem(label, key)
        self.units.setToolTip(
            "Units used by the script; the captured model is converted to "
            "Studio's kN-mm base units")
        row.addWidget(self.units)
        row.addStretch(1)
        self.load_model = QPushButton("Current Studio Model (Tcl)")
        self.load_model.setToolTip(
            "Put the current Studio model into the editor as an OpenSees Tcl script")
        row.addWidget(self.load_model)
        self.run_button = QPushButton("Run")
        self.run_button.setDefault(True)
        self.run_button.setToolTip("Run the script (Ctrl+Enter)")
        row.addWidget(self.run_button)
        lay.addLayout(row)

        capture_row = QHBoxLayout()
        self.auto_load = QCheckBox("Load captured model into Studio after run")
        self.auto_load.setChecked(True)
        capture_row.addWidget(self.auto_load)
        self.capture_label = QLabel("No model captured yet.")
        self.capture_label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        capture_row.addWidget(self.capture_label)
        capture_row.addStretch(1)
        self.import_button = QPushButton("Import Captured Model")
        self.import_button.setEnabled(False)
        capture_row.addWidget(self.import_button)
        lay.addLayout(capture_row)

        split = QSplitter(Qt.Vertical)
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas", 9))
        self.editor.setTabStopDistance(32)
        self.editor.setPlainText(PYTHON_SAMPLE)
        split.addWidget(self.editor)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Consolas", 9))
        self.output.setPlaceholderText("Script output")
        split.addWidget(self.output)
        split.setSizes([420, 180])
        lay.addWidget(split, 1)

        hint = QLabel(
            "Scripts run in the shared OpenSees domain. Model commands "
            "(node, element, fix, materials, sections, patterns and loads) are "
            "captured and converted to Studio units when you import them. "
            "Tcl supports model commands but not loops, procedures or variables.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        lay.addWidget(hint)

        self.language.currentIndexChanged.connect(self._language_changed)
        self.run_button.clicked.connect(self.run)
        self.load_model.clicked.connect(self._load_current_model)
        self.import_button.clicked.connect(self.emit_captured_model)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.run)

    def _language_changed(self, index: int) -> None:
        old = "tcl" if self.language.itemData(index) == "python" else "python"
        self._texts[old] = self.editor.toPlainText()
        self.editor.setPlainText(self._texts.get(
            self.language.currentData(), ""))

    def _load_current_model(self) -> None:
        self.language.setCurrentIndex(self.language.findData("tcl"))
        self.editor.setPlainText(opsgen.export_tcl(self.project))
        self.output.setPlainText("Current Studio model loaded as Tcl.")

    def run(self) -> None:
        code = self.editor.toPlainText()
        language = self.language.currentData()
        recorder = scriptmodel.ScriptModelRecorder(self.units.currentData())
        self.output.appendPlainText(f"--- run {language} ---")
        try:
            if language == "python":
                result = tcl.run_python(code, recorder=recorder)
            else:
                result = tcl.run_tcl(code, recorder=recorder)
            text = result.get("output", "")
            if text:
                self.output.appendPlainText(text.rstrip())
            if result.get("commands"):
                self.output.appendPlainText(
                    f"[{result['commands']} command(s) executed]")
        except Exception as exc:  # noqa: BLE001 - show it in the console
            detail = traceback.format_exc() if language == "python" else str(exc)
            self.output.appendPlainText(f"ERROR: {detail.rstrip()}")
        finally:
            self._capture(recorder)
        self.output.verticalScrollBar().setValue(
            self.output.verticalScrollBar().maximum())

    def _capture(self, recorder) -> None:
        project = recorder.build()
        if not project.nodes:
            self.capture_label.setText("No model commands were captured.")
            self._last_project = None
            self.import_button.setEnabled(False)
            return
        counts = recorder.element_count
        self._last_project = project
        self._last_summary = (f"Script model: {len(project.nodes)} nodes, "
                              f"{len(project.elements)} elements, "
                              f"{len(project.nodal_loads) + len(project.elem_loads)} loads")
        self.capture_label.setText(self._last_summary)
        self.import_button.setEnabled(True)
        if recorder.warnings:
            self.output.appendPlainText(
                "Capture warnings: " + "; ".join(recorder.warnings[:8]))
        self.output.appendPlainText(
            f"[captured {len(project.nodes)} nodes, {counts} elements]")
        if self.auto_load.isChecked():
            self.emit_captured_model()

    def emit_captured_model(self) -> None:
        if self._last_project is not None:
            self.modelReady.emit(self._last_project, self._last_summary)
