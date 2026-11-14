"""Script console: write and run OpenSeesPy Python or OpenSees Tcl."""

from __future__ import annotations

import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout)

from . import opsgen, theme, tcl

PYTHON_SAMPLE = """# OpenSeesPy scripting console.
# The app rebuilds its own model before each analysis, so experiments here
# do not modify the Studio project.
ops.wipe()
ops.model("BasicBuilder", "-ndm", 3, "-ndf", 6)
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 1000.0, 0.0, 0.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)
ops.uniaxialMaterial("Elastic", 1, 200.0)
ops.geomTransf("Linear", 1, 0.0, 0.0, 1.0)
ops.element("elasticBeamColumn", 1, 1, 2, 1.0e4, 200.0, 80.0, 1.0e6,
            1.0e6, 1.0e6, 1)
print("nodes:", ops.getNodeTags())
"""

TCL_SAMPLE = """# OpenSees Tcl scripting console (model commands; no loops or variables).
wipe
model BasicBuilder -ndm 3 -ndf 6
node 1 0.0 0.0 0.0
node 2 1000.0 0.0 0.0
fix 1 1 1 1 1 1 1
uniaxialMaterial Elastic 1 200.0
geomTransf Linear 1 0.0 0.0 1.0
element elasticBeamColumn 1 1 2 1.0e4 200.0 80.0 1.0e6 1.0e6 1.0e6 1
puts "Tcl model built"
"""


class ScriptConsoleDialog(QDialog):
    """One window for Python (OpenSeesPy) and Tcl scripts."""

    def __init__(self, project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Script Console")
        self.resize(880, 640)
        self.project = project
        self._texts = {"python": PYTHON_SAMPLE, "tcl": TCL_SAMPLE}

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Language"))
        self.language = QComboBox()
        self.language.addItem("Python (OpenSeesPy)", "python")
        self.language.addItem("Tcl (OpenSees commands)", "tcl")
        row.addWidget(self.language)
        row.addStretch(1)
        self.load_model = QPushButton("Load Current Model (Tcl)")
        self.load_model.setToolTip(
            "Put the current Studio model into the editor as an OpenSees Tcl script")
        row.addWidget(self.load_model)
        self.run_button = QPushButton("Run")
        self.run_button.setDefault(True)
        self.run_button.setToolTip("Run the script (Ctrl+Enter)")
        row.addWidget(self.run_button)
        lay.addLayout(row)

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
            "Runs in the shared OpenSees domain, not in the Studio project. "
            "Tcl supports model and analysis commands but not loops, "
            "procedures or variables.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        lay.addWidget(hint)

        self.language.currentIndexChanged.connect(self._language_changed)
        self.run_button.clicked.connect(self.run)
        self.load_model.clicked.connect(self._load_current_model)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.run)

    def _language_changed(self, index: int) -> None:
        old = "tcl" if self.language.itemData(index) == "python" else "python"
        self._texts[old] = self.editor.toPlainText()
        self.editor.setPlainText(self._texts.get(
            self.language.currentData(), ""))

    def _load_current_model(self) -> None:
        self.language.setCurrentIndex(self.language.findData("tcl"))
        self.editor.setPlainText(opsgen.export_tcl(self.project))
        self.output.setPlainText("Current model loaded as Tcl.")

    def run(self) -> None:
        code = self.editor.toPlainText()
        language = self.language.currentData()
        self.output.appendPlainText(f"--- run {language} ---")
        try:
            if language == "python":
                result = tcl.run_python(code)
            else:
                result = tcl.run_tcl(code)
            text = result.get("output", "")
            if text:
                self.output.appendPlainText(text.rstrip())
            if result.get("commands"):
                self.output.appendPlainText(
                    f"[{result['commands']} command(s) executed]")
        except Exception as exc:  # noqa: BLE001 - show it in the console
            detail = traceback.format_exc() if language == "python" else str(exc)
            self.output.appendPlainText(f"ERROR: {detail.rstrip()}")
        self.output.verticalScrollBar().setValue(
            self.output.verticalScrollBar().maximum())
