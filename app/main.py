"""OpenSees Studio - application entry point."""

from __future__ import annotations

import os
import sys
import traceback


def _guard_streams() -> None:
    """PyInstaller windowed builds have no stdout/stderr; give them sinks."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


_guard_streams()

def _selftest(report_path: str) -> int:
    """Headless end-to-end check used to verify the packaged executable."""
    import math

    from . import opsgen
    from .model import (ElementLoad, Element, LoadCase, LoadCombination,
                        NodalLoad, Node, Section, TimeHistoryCase,
                        ResponseSpectrumCase, default_project)

    lines = []

    def emit(text):
        lines.append(text)

    try:
        p = default_project()
        p.materials[1].E = 200.0
        p.materials[1].rho = 7.85e-9
        s = p.sections[1]
        s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
        s.compute()
        p.nodes[1] = Node(1, 0, 0, 0, [True] * 6)
        p.nodes[2] = Node(2, 4000, 0, 0)
        p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[0, 0, 1])
        p.cases["DL"] = LoadCase("DL")
        p.nodal_loads.append(NodalLoad(1, 2, "DL", [0, 0, 10, 0, 0, 0]))
        r = opsgen.run_static(p, "DL")
        want = 10.0 * 4000 ** 3 / (3 * 200.0 * s.Iy)
        got = r.displacements[2][2]
        emit(f"static tip displacement: {got:.6f} mm (expected {want:.6f})")
        assert abs(got - want) < 1e-6 * want, "static displacement mismatch"
        f = r.element_forces[1]
        emit(f"base moment My: {f[4]:.3f} kN.mm (expected {40000:.3f})")
        assert abs(abs(f[4]) - 40000) < 1e-3 * 40000, "element force mismatch"

        m = opsgen.run_modal(p, 3)
        emit(f"modal periods: {[round(x.period, 5) for x in m.modes]}")
        assert m.modes and m.modes[0].period > 0, "no modal results"

        tcl = opsgen.export_tcl(p)
        assert "elasticBeamColumn" in tcl and "pattern Plain" in tcl
        emit(f"tcl export: {len(tcl.splitlines())} lines")

        combo = LoadCombination("C", [("DL", 1.4)])
        p.combos["C"] = combo
        rc = opsgen.run_static(p, "C")
        emit(f"combination factor 1.4 -> {rc.displacements[2][2]:.6f} mm")
        assert abs(rc.displacements[2][2] - 1.4 * got) < 1e-6 * abs(got), "combination scaling"

        p.time_history = TimeHistoryCase(
            source="sine", dt=0.01, n_steps=20, direction=1,
            damping_ratio=0.05, sine_amplitude=0.10, sine_period=1.0)
        th = opsgen.run_time_history(p)
        emit(f"time history: {th.n_steps} steps, peak {th.peak_disp:.6f} mm")
        assert th.n_steps == 20 and th.peak_disp > 0.0, "time-history result"

        p.response_spectrum = ResponseSpectrumCase(
            direction=3, n_modes=2, periods=[0.0, 0.2, 0.5, 1.0],
            accelerations=[0.4, 0.8, 0.6, 0.3])
        rs = opsgen.run_response_spectrum(p)
        emit(f"response spectrum: {rs.n_modes} modes, peak {rs.peak_disp:.6f} mm")
        assert rs.n_modes >= 1 and rs.peak_disp > 0.0, "response-spectrum result"

        from .hinge_catalog import MATERIALS, image_path
        expected_images = [m.key for m in MATERIALS.values() if m.image]
        missing = [key for key in expected_images if not image_path(key)]
        assert not missing, f"missing hinge reference images: {missing}"
        emit(f"hinge reference images: {len(expected_images)} embedded")

        emit("RESULT: PASS")
        code = 0
    except Exception as exc:  # pragma: no cover - diagnostics
        emit("RESULT: FAIL")
        emit(f"{type(exc).__name__}: {exc}")
        emit(traceback.format_exc())
        code = 1

    text = "\n".join(lines)
    try:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    try:
        print(text)
    except Exception:
        pass
    return code


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)

    if "--analysis-child" in argv:
        idx = argv.index("--analysis-child")
        from .analysis_child import main as child_main

        return child_main(argv[idx + 1:])

    if "--selftest" in argv:
        i = argv.index("--selftest")
        report = "selftest_report.txt"
        if "--report" in argv:
            report = argv[argv.index("--report") + 1]
        return _selftest(report)

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "OpenSeesStudio.App.1")
        except Exception:
            pass

    from PySide6.QtWidgets import QApplication

    from . import icons, theme
    from .mainwindow import MainWindow

    app = QApplication(argv)
    app.setApplicationName("OpenSees Studio")
    app.setOrganizationName("OpenSees Studio")
    theme.apply_theme(app)
    app.setWindowIcon(icons.app_icon())

    win = MainWindow()
    win.show()

    if "--bridge" in argv:
        from .bridge import GuiBridge

        idx = argv.index("--bridge")
        port = 8765
        if idx + 1 < len(argv) and argv[idx + 1].isdigit():
            port = int(argv[idx + 1])
        bridge = GuiBridge(win, port)
        ok, err = bridge.start()
        win.bridge = bridge
        if ok:
            win._log(f"MCP bridge listening on 127.0.0.1:{port}")
            win.statusBar().showMessage(f"MCP bridge: 127.0.0.1:{port}")
        else:
            win._log(f"MCP bridge failed to start: {err}")

    if "--example" in argv:
        win.load_example()
    if "--open" in argv:
        win.open_path(argv[argv.index("--open") + 1])
    if "--run" in argv:
        from . import opsgen

        scenario = win.scenario_combo.currentText()
        res = opsgen.run_static(win.project, scenario)
        win.static_results = res
        win.static_cache[scenario] = res
        win.results_scenario = scenario
        win.viewport.set_load_scenario(scenario)
        win.viewport.set_static_results(res)
        win.results_panel.set_current_scenario(scenario)
        win.viewport.fit()
        win._log(f"Static analysis '{scenario}' complete. Max |u| = {res.max_disp:.4f} mm")

    if "--screenshot" in argv:
        from PySide6.QtCore import QTimer

        out = argv[argv.index("--screenshot") + 1]

        def shot():
            win.grab().save(out)
            app.quit()

        QTimer.singleShot(1200, shot)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
