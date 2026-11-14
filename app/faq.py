"""FAQ dialog with answers grounded in the official OpenSees documentation."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QTextBrowser, QVBoxLayout)

from . import theme

WIKI = "https://opensees.berkeley.edu/wiki/index.php/Main_Page"
GETTING_STARTED = "https://opensees.berkeley.edu/wiki/index.php/Getting_Started"
COMMAND_MANUAL = ("https://opensees.berkeley.edu/OpenSees/manuals/usermanual/"
                  "OpenSeesCommandLanguageManualJune2006.pdf")
OPENSEESPY = "https://openseespy.github.io/"
DOCS = "https://opensees.github.io/OpenSeesDocumentation/"

FAQ_HTML = f"""
<style>
  h2 {{ color: {theme.ACCENT_DARK}; font-size: 14px; margin-top: 14px; }}
  h3 {{ color: {theme.ACCENT_DARK}; font-size: 12px; margin-top: 12px; }}
  p, li {{ font-size: 12px; }}
  code {{ background: #eef3f8; padding: 1px 3px; }}
</style>

<p>OpenSees itself has no embedded help window. These answers summarize the
official OpenSees documentation and link to it at the bottom. Studio-specific
behaviour is marked <b>Studio</b>.</p>

<h2>Model and units</h2>
<h3>What unit system does OpenSees use?</h3>
<p>OpenSees is unit-agnostic: any consistent set works. A common set is
m, kN, kPa, t. <b>Studio</b> stores models in <b>kN, mm, tonne, s</b> and converts
display units (m/mm, kN/kip, …) only for input and tables. Keep E in kN/mm²
(200 = 200 GPa) and distributed loads in kN/mm (10 kN/m = 0.01).</p>

<h3>Why does a 2D model become unstable in a 3D program?</h3>
<p>A 2D model has no out-of-plane stiffness. When it is embedded in 3D space,
out-of-plane translations and rotations at the supports must be restrained.
<b>Studio</b> does this automatically when it captures a 2D script model; for
hand-built 3D models, add those restraints explicitly.</p>

<h2>Analysis and errors</h2>
<h3>“Matrix singular”, “failed to solve” or a huge displacement</h3>
<ul>
<li>A node or DOF is unrestrained (rigid-body mode), or a support is missing.</li>
<li>Nodes are disconnected from elements, or an element has zero area/inertia.</li>
<li>A 2D model lacks out-of-plane restraint in 3D.</li>
<li>Two nodes share the same coordinates and create a zero-length element.</li>
</ul>
<p>Run <b>Model Check</b> first: it reports orphan nodes, missing references and
support/load problems. A displacement near 10¹⁵ almost always means a singular
mode, not a large real deflection.</p>

<h3>Why does modal analysis fail?</h3>
<p>Eigenvalue analysis needs mass. <b>Studio</b> builds lumped masses from
material densities; a model whose materials have zero density has no mass.
Set a realistic density (steel 7.85e-9 t/mm³, concrete 2.5e-9 t/mm³).</p>

<h3>Why does a nonlinear analysis stop converging?</h3>
<p>OpenSees uses the analysis objects you define: <code>constraints</code>,
<code>numberer</code>, <code>system</code>, <code>test</code>,
<code>algorithm</code> and <code>integrator</code>. Typical fixes are a looser
test tolerance, more iterations, <code>NewtonLineSearch</code> or
<code>ModifiedNewton</code>, smaller load/time steps, or a different system
solver. Studio’s pushover and time-history drivers set these internally.</p>

<h2>Nonlinear and dynamic</h2>
<h3>When is pushover available?</h3>
<p>Pushover needs lumped plastic hinges assigned to beam elements and a lateral
load case or combination. <b>Studio</b> creates fibre hinges with
<code>beamWithHinges</code>; unassigned elements stay elastic. Define hinges in
<b>Pushover &gt; Define Hinges</b>, assign them in <b>Assign Hinges</b>, then run
pushover with a gravity case and a lateral case.</p>

<h3>Which ground-motion files can be read?</h3>
<p>PEER AT2/NGA files, two-column time–acceleration files, and single-column
acceleration files with a user-supplied time step. The time step and number of
points are read automatically where available. The ground motion must be
consistent with the model’s time unit (seconds).</p>

<h3>What do SRSS and CQC mean?</h3>
<p>They combine modal response-spectrum maxima: SRSS is the square root of the
sum of squares (modes treated as uncoupled); CQC includes modal correlation and
is preferable for closely spaced modes. Increase the number of modes until the
cumulative mass ratio is high enough.</p>

<h2>Studio features</h2>
<h3>Why is the model locked after an analysis?</h3>
<p>Results correspond to the solved model. <b>Studio</b> locks editing so results
cannot silently become stale; press <b>Ctrl+L</b> to unlock. Any model change
clears the results.</p>

<h3>Does Import Tcl run a full Tcl interpreter?</h3>
<p>No. It reads model commands: nodes, supports, materials, sections,
<code>geomTransf</code>, beam/truss/ShellMITC4 elements and <code>pattern</code>
loads. Loops, procedures, variables and <code>expr</code> are not evaluated.
Commands that are skipped are listed in the message log.</p>

<h3>Why did my script not draw in Studio?</h3>
<p>Before 1.0.4 the Script Console only ran OpenSeesPy/Tcl and did not modify the
Studio project. From 1.0.4 it captures model-building commands, converts the
chosen script units to kN-mm, and loads the captured model into the viewport.
Use <b>Load captured model into Studio</b> or the auto-load checkbox.</p>

<h3>How do I use an AI agent with Studio?</h3>
<p>The installed <code>mcp/OpenSeesStudioMCP.exe</code> exposes the model and
analysis tools over MCP stdio. With the GUI started using <code>--bridge</code>,
<code>gui_connect</code> mirrors changes live and <code>gui_screenshot</code>
returns the viewport.</p>

<h2>Official OpenSees help</h2>
<ul>
<li><a href="{WIKI}">OpenSees Wiki</a></li>
<li><a href="{GETTING_STARTED}">Getting Started with OpenSees</a></li>
<li><a href="{COMMAND_MANUAL}">OpenSees Command Language Manual (PDF)</a></li>
<li><a href="{OPENSEESPY}">OpenSeesPy documentation</a></li>
<li><a href="{DOCS}">OpenSees documentation (commands and materials)</a></li>
</ul>
"""


class FaqDialog(QDialog):
    """Scrollable FAQ with links to the official OpenSees documentation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenSees Studio - FAQ")
        self.resize(820, 680)
        lay = QVBoxLayout(self)
        title = QLabel("Frequently asked questions")
        title.setStyleSheet(
            f"font-size:15px; font-weight:600; color:{theme.ACCENT_DARK};")
        lay.addWidget(title)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(FAQ_HTML)
        lay.addWidget(self.browser, 1)

        row = QHBoxLayout()
        for label, url in (("OpenSees Wiki", WIKI),
                           ("Getting Started", GETTING_STARTED),
                           ("Command Manual", COMMAND_MANUAL),
                           ("OpenSeesPy Docs", OPENSEESPY)):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, target=url:
                QDesktopServices.openUrl(QUrl(target)))
            row.addWidget(button)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
