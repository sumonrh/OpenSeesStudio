"""Child-process analysis runner tests (source-tree child)."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("OPENSEES_STUDIO_IN_PROCESS", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.analysis_runner import AnalysisRunner
from app.model import (Element, Node, NodalLoad, Project, ResponseSpectrumCase,
                       TimeHistoryCase, default_project)

app = QApplication.instance() or QApplication([])


def run_case(project, kind, config):
    runner = AnalysisRunner()
    loop = QEventLoop()
    outcome = {}

    def done(result):
        outcome["result"] = result
        loop.quit()

    def failed(message):
        outcome["error"] = message
        loop.quit()

    runner.finished.connect(done)
    runner.failed.connect(failed)
    QTimer.singleShot(120000, loop.quit)
    runner.run(project, kind, config)
    loop.exec()
    return outcome


def base_project():
    p = default_project()
    p.materials[1].E = 200.0
    p.materials[1].rho = 7.85e-9
    s = p.sections[1]
    s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
    s.compute()
    p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
    p.nodes[2] = Node(2, 3000, 0, 0)
    p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[0, 0, 1])
    p.nodal_loads = [NodalLoad(1, 2, "DL", [10.0, 0.0, 0.0, 0.0, 0.0, 0.0])]
    return p


def main():
    failures = []

    p = base_project()
    outcome = run_case(p, "static", {"scenario": "DL"})
    result = outcome.get("result")
    if result is None:
        failures.append("static child run")
        print("FAIL static child run:", outcome.get("error", "timeout"))
    else:
        print("PASS static child run:", result.max_disp)
        if not (result.max_disp > 0.0):
            failures.append("static result")

    p = base_project()
    p.time_history = TimeHistoryCase(source="sine", dt=0.01, n_steps=20,
                                     direction=1, damping_ratio=0.05,
                                     sine_amplitude=0.10, sine_period=1.0)
    outcome = run_case(p, "time_history", {})
    result = outcome.get("result")
    if result is None:
        failures.append("time-history child run")
        print("FAIL time-history child run:", outcome.get("error", "timeout"))
    else:
        print("PASS time-history child run:", result.n_steps, result.peak_disp)
        if result.n_steps != 20 or result.peak_disp <= 0.0:
            failures.append("time-history result")

    p = base_project()
    p.response_spectrum = ResponseSpectrumCase(
        direction=3, n_modes=2, periods=[0.0, 0.2, 0.5, 1.0],
        accelerations=[0.4, 0.8, 0.6, 0.3])
    outcome = run_case(p, "response_spectrum", {})
    result = outcome.get("result")
    if result is None:
        failures.append("response-spectrum child run")
        print("FAIL response-spectrum child run:",
              outcome.get("error", "timeout"))
    else:
        print("PASS response-spectrum child run:",
              result.n_modes, result.peak_disp)
        if result.n_modes < 1 or result.peak_disp <= 0.0:
            failures.append("response-spectrum result")

    if failures:
        print("FAILURES:", failures)
        return 1
    print("ALL ANALYSIS RUNNER TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
