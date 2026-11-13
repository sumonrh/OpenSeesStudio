"""Run analyses in a child process and report progress in a small dialog.

The OpenSees solver is deliberately kept out of the GUI process: a hard crash
inside the solver terminates the child, not OpenSees Studio.  The child is
``app.analysis_child`` in the source tree and the same executable with
``--analysis-child`` in the frozen build.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout)

from . import opsgen
from .model import Project

_CREATE_NO_WINDOW = 0x08000000


def _int_keyed(value: Any) -> dict:
    return {int(key): item for key, item in (value or {}).items()}


def _static_result(d: dict) -> opsgen.StaticResults:
    return opsgen.StaticResults(
        scenario=str(d.get("scenario", "")),
        displacements=_int_keyed(d.get("displacements")),
        reactions=_int_keyed(d.get("reactions")),
        element_forces=_int_keyed(d.get("element_forces")),
        element_kind=_int_keyed(d.get("element_kind")),
        max_disp=float(d.get("max_disp", 0.0)),
        log=str(d.get("log", "")))


def _modal_result(d: dict) -> opsgen.ModalResults:
    modes = [opsgen.ModeResult(**m) for m in d.get("modes", [])]
    shapes = {
        int(mode): {int(node): list(values)
                    for node, values in (shape or {}).items()}
        for mode, shape in (d.get("shapes") or {}).items()
    }
    return opsgen.ModalResults(modes=modes, shapes=shapes,
                               log=str(d.get("log", "")))


def _pushover_result(d: dict) -> opsgen.PushoverResults:
    steps = []
    for raw in d.get("steps", []):
        steps.append(opsgen.PushoverStep(
            step=int(raw.get("step", 0)),
            displacement=float(raw.get("displacement", 0.0)),
            base_shear=float(raw.get("base_shear", 0.0)),
            displacements=_int_keyed(raw.get("displacements")),
            hinge_rotations=_int_keyed(raw.get("hinge_rotations")),
            hinge_moments=_int_keyed(raw.get("hinge_moments"))))
    return opsgen.PushoverResults(
        gravity_case=str(d.get("gravity_case", "")),
        lateral_case=str(d.get("lateral_case", "")),
        control_node=int(d.get("control_node", 0)),
        control_dof=int(d.get("control_dof", 1)),
        hinge_model=str(d.get("hinge_model", "")),
        steps=steps,
        hinge_yield={int(k): float(v)
                     for k, v in (d.get("hinge_yield") or {}).items()},
        log=str(d.get("log", "")))


def _time_history_result(d: dict) -> opsgen.TimeHistoryResults:
    return opsgen.TimeHistoryResults(
        case_name=str(d.get("case_name", "")),
        ground_motion=str(d.get("ground_motion", "")),
        direction=int(d.get("direction", 1)),
        dt=float(d.get("dt", 0.0)),
        n_steps=int(d.get("n_steps", 0)),
        n_steps_requested=int(d.get("n_steps_requested", 0)),
        time=[float(v) for v in d.get("time", [])],
        node_disp=_int_keyed(d.get("node_disp")),
        node_vel=_int_keyed(d.get("node_vel")),
        node_accel=_int_keyed(d.get("node_accel")),
        peak_disp=float(d.get("peak_disp", 0.0)),
        peak_vel=float(d.get("peak_vel", 0.0)),
        peak_accel=float(d.get("peak_accel", 0.0)),
        log=str(d.get("log", "")))


_RESULT_BUILDERS = {
    "static": _static_result,
    "modal": _modal_result,
    "pushover": _pushover_result,
    "time_history": _time_history_result,
}


class AnalysisRunner(QObject):
    """Start, monitor and cancel one child-process analysis."""

    started = Signal(str)
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: Optional[QProcess] = None
        self._job_dir: Optional[Path] = None
        self._result_path: Optional[Path] = None
        self._stdout = ""
        self._stderr = ""
        self._error = ""
        self._cancelled = False
        self._result: object = None
        self._completed = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and (
            self._process.state() != QProcess.ProcessState.NotRunning)

    @property
    def result(self):
        return self._result

    @property
    def completed(self) -> bool:
        """True for an in-process run that has already finished."""
        return self._completed

    def run(self, project: Project, kind: str, config: Optional[dict] = None) -> None:
        if self.is_running:
            raise RuntimeError("Another analysis is already running.")
        self._result = None
        self._completed = False
        self._error = ""
        self._stderr = ""
        self._stdout = ""
        self._cancelled = False
        if os.environ.get("OPENSEES_STUDIO_IN_PROCESS") == "1":
            self._run_in_process(project, kind, config or {})
            return
        self._job_dir = Path(tempfile.mkdtemp(prefix="osstudio_job_"))
        job_path = self._job_dir / "job.json"
        self._result_path = self._job_dir / "result.json"
        job_path.write_text(json.dumps({
            "kind": kind,
            "project": project.to_dict(),
            "config": config or {},
        }, indent=2), encoding="utf-8")

        process = QProcess(self)
        process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        process.setProcessEnvironment(env)
        if getattr(sys, "frozen", False):
            process.setProgram(sys.executable)
            process.setArguments(["--analysis-child", str(job_path),
                                  str(self._result_path)])
        else:
            process.setProgram(sys.executable)
            process.setArguments(["-m", "app.analysis_child", str(job_path),
                                  str(self._result_path)])
        modifier = getattr(process, "setCreateProcessArgumentsModifier", None)
        if modifier is not None and os.name == "nt":
            def _hide(args: object) -> None:
                args.flags |= _CREATE_NO_WINDOW  # type: ignore[attr-defined]
            modifier(_hide)

        process.readyReadStandardOutput.connect(self._on_stdout)
        process.readyReadStandardError.connect(self._on_stderr)
        process.started.connect(lambda: self.started.emit(kind))
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        process.start()

    def cancel(self) -> None:
        if not self.is_running or self._process is None:
            return
        self._cancelled = True
        self.log.emit("Cancelling analysis ...")
        self._process.terminate()
        QTimer.singleShot(1500, self._kill_if_alive)

    def _progress(self, step: int, total: int) -> None:
        self.progress.emit(int(step), int(total))

    def _run_in_process(self, project: Project, kind: str,
                        config: dict) -> None:
        """Test/debug path: run in the GUI process, synchronously."""
        self.started.emit(kind)
        self.log.emit("Running in-process (OPENSEES_STUDIO_IN_PROCESS=1).")
        try:
            if kind == "static":
                result = opsgen.run_static(project, str(config["scenario"]))
            elif kind == "modal":
                result = opsgen.run_modal(project, int(config.get("nmodes", 6)))
            elif kind == "pushover":
                result = opsgen.run_pushover(project, config,
                                             progress=self._progress)
            elif kind == "time_history":
                result = opsgen.run_time_history(project, config,
                                                 progress=self._progress)
            else:
                raise ValueError(f"Unknown analysis kind: {kind}")
            self._result = result
            self._completed = True
            self.finished.emit(result)
        except Exception as exc:
            self._error = str(exc)
            self._completed = True
            self.failed.emit(str(exc))

    def _kill_if_alive(self) -> None:
        if self.is_running and self._process is not None:
            self._process.kill()

    def _on_stdout(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode(
            "utf-8", errors="replace")
        self._stdout += chunk
        while "\n" in self._stdout:
            line, self._stdout = self._stdout.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                self.log.emit(line)
                continue
            kind = payload.get("type")
            if kind == "log":
                self.log.emit(str(payload.get("message", "")))
            elif kind == "progress":
                self.progress.emit(int(payload.get("step", 0)),
                                   int(payload.get("total", 0)))
            elif kind == "started":
                self.started.emit(str(payload.get("kind", "")))
            elif kind == "error":
                self._error = str(payload.get("message", ""))
                self.log.emit(f"Error: {self._error}")
            elif kind == "done":
                self.log.emit("Analysis process finished.")

    def _on_stderr(self) -> None:
        if self._process is None:
            return
        self._stderr += bytes(self._process.readAllStandardError()).decode(
            "utf-8", errors="replace")

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.failed.emit(
                "The analysis process could not start.\n"
                f"{self._stderr.strip()[-4000:]}")
            self._cleanup()

    def _on_finished(self, code: int, _status) -> None:
        if self._cancelled:
            self._cleanup()
            self.cancelled.emit()
            return
        if code == 0 and self._result_path is not None:
            try:
                payload = json.loads(
                    self._result_path.read_text(encoding="utf-8"))
                kind = str(payload.get("kind", ""))
                builder = _RESULT_BUILDERS.get(kind)
                if builder is None:
                    raise ValueError(f"Unknown result kind: {kind}")
                self._result = builder(dict(payload.get("result") or {}))
                self._cleanup()
                self.finished.emit(self._result)
                return
            except Exception as exc:
                self._error = str(exc)
        tail = self._stderr.strip()
        message = self._error or "The analysis process failed."
        if tail:
            message += "\n\n" + "\n".join(tail.splitlines()[-30:])
        self._cleanup()
        self.failed.emit(message)

    def _cleanup(self) -> None:
        if self._job_dir is not None:
            shutil.rmtree(self._job_dir, ignore_errors=True)
        self._job_dir = None
        self._result_path = None
        self._process = None


class AnalysisProgressDialog(QDialog):
    """Modal progress/log window used while the child analysis runs."""

    def __init__(self, title: str, runner: AnalysisRunner, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 430)
        self.runner = runner
        lay = QVBoxLayout(self)
        self.status = QLabel("Starting analysis ...")
        self.status.setStyleSheet("font-weight: 600;")
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.cancel_btn = QPushButton("Cancel")
        buttons.addButton(self.cancel_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.cancel_btn.clicked.connect(runner.cancel)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        self.close_btn.setEnabled(False)

        runner.started.connect(self._on_started)
        runner.log.connect(self._on_log)
        runner.progress.connect(self._on_progress)
        runner.finished.connect(self._on_finished)
        runner.failed.connect(self._on_failed)
        runner.cancelled.connect(self._on_cancelled)

    def _on_started(self, kind: str) -> None:
        self.status.setText(f"Running {kind.replace('_', ' ')} analysis ...")

    def _on_log(self, message: str) -> None:
        if message:
            self.log.appendPlainText(message)

    def _on_progress(self, step: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(step)

    def _on_finished(self, _result: object) -> None:
        self.status.setText("Analysis complete.")
        self.accept()

    def _on_failed(self, message: str) -> None:
        self.status.setText("Analysis failed.")
        self.log.appendPlainText(message)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

    def _on_cancelled(self) -> None:
        self.status.setText("Analysis cancelled.")
        self.reject()

    def closeEvent(self, event) -> None:
        if self.runner.is_running:
            self.runner.cancel()
            event.ignore()
            return
        super().closeEvent(event)
