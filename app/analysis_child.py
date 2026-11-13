"""Headless analysis child process.

Usage (source tree):
    python -m app.analysis_child job.json result.json
Frozen executable:
    OpenSeesStudio.exe --analysis-child job.json result.json

The child writes JSON progress lines to stdout and the result dataclass as
JSON to ``result.json``.  A non-zero exit code means the run failed; stderr
carries the traceback.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import traceback
from pathlib import Path

from . import opsgen
from .model import Project


def _emit(event: str, **payload) -> None:
    print(json.dumps({"type": event, **payload}), flush=True)


def _progress(step: int, total: int) -> None:
    _emit("progress", step=int(step), total=int(total))


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("analysis_child: expected job.json and result.json", file=sys.stderr)
        return 2
    job_path, result_path = Path(args[0]), Path(args[1])
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        project = Project.from_dict(job["project"])
        kind = str(job["kind"])
        config = dict(job.get("config") or {})
        _emit("started", kind=kind)

        if kind == "static":
            results = opsgen.run_static(project, str(config["scenario"]))
            _progress(1, 1)
        elif kind == "modal":
            results = opsgen.run_modal(project, int(config.get("nmodes", 6)))
            _progress(1, 1)
        elif kind == "pushover":
            results = opsgen.run_pushover(project, config, progress=_progress)
        elif kind == "time_history":
            results = opsgen.run_time_history(project, config,
                                              progress=_progress)
        else:
            raise ValueError(f"Unknown analysis kind: {kind}")

        payload = {"kind": kind, "result": dataclasses.asdict(results)}
        result_path.write_text(json.dumps(payload, indent=2),
                               encoding="utf-8")
        _emit("done", kind=kind)
        return 0
    except Exception as exc:
        _emit("error", message=str(exc))
        traceback.print_exc()
        try:
            result_path.write_text(
                json.dumps({"error": str(exc)}, indent=2), encoding="utf-8")
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
